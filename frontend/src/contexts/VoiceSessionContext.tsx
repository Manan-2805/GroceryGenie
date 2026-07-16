import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

export type VoiceSessionState = {
  status: 'idle' | 'transcribing' | 'thinking' | 'speaking' | 'waiting_permission';
  transcript: string;
  isConnecting: boolean;
  isConnected: boolean;
  permissionRequest: {
    action: string;
    summary: string;
    payload: unknown;
  } | null;
  error: string | null;
};

type VoiceSessionContextType = {
  state: VoiceSessionState;
  startSession: (sessionId?: string) => Promise<void>;
  endSession: (clearError?: boolean) => void;
  sendPermissionResponse: (approved: boolean) => void;
};

type VoiceMessage = {
  type?: string;
  action?: string;
  summary?: string;
  payload?: unknown;
  status?: VoiceSessionState['status'];
  text?: string;
  navigate_to?: string;
  navigate_label?: string;
  session_id?: string;
};

const VoiceSessionContext = createContext<VoiceSessionContextType | null>(null);

export const useVoiceSession = () => {
  const context = useContext(VoiceSessionContext);
  if (!context) {
    throw new Error('useVoiceSession must be used within a VoiceSessionProvider');
  }
  return context;
};

export const VoiceSessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<VoiceSessionState>({
    status: 'idle',
    transcript: '',
    isConnecting: false,
    isConnected: false,
    permissionRequest: null,
    error: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorNodeRef = useRef<ScriptProcessorNode | null>(null);
  const audioQueueRef = useRef<Float32Array[]>([]);
  const isPlayingRef = useRef<boolean>(false);
  const nextPlayTimeRef = useRef<number>(0);
  const audioSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const handleIncomingAudioChunkRef = useRef<(buffer: ArrayBuffer) => void>(() => {
    throw new Error('Audio handler is not initialized');
  });

  const stopAllAudioPlayback = useCallback(() => {
    audioSourcesRef.current.forEach((src) => {
      try {
        src.stop();
      } catch {
        // Already stopped
      }
    });
    audioSourcesRef.current = [];
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    nextPlayTimeRef.current = 0;
  }, []);

  const endSession = useCallback(
    (clearError = true) => {
      if (processorNodeRef.current) {
        processorNodeRef.current.disconnect();
        processorNodeRef.current = null;
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((track) => track.stop());
        mediaStreamRef.current = null;
      }

      stopAllAudioPlayback();

      if (wsRef.current) {
        if (wsRef.current.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'end_session' }));
        }
        wsRef.current.close();
        wsRef.current = null;
      }

      if (audioContextRef.current) {
        audioContextRef.current.close().catch((error: unknown) => {
          console.error('Failed to close the audio context', error);
        });
        audioContextRef.current = null;
      }

      setState((prev) => ({
        status: 'idle',
        transcript: '',
        isConnecting: false,
        isConnected: false,
        permissionRequest: null,
        error: clearError ? null : prev.error,
      }));
    },
    [stopAllAudioPlayback]
  );

  const startSession = useCallback(
    async (sessionId?: string) => {
      if (wsRef.current) return;

      setState((prev) => ({ ...prev, isConnecting: true, transcript: '', error: null }));

      try {
        const AudioContextClass =
          window.AudioContext ??
          (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (AudioContextClass === undefined) {
          throw new Error('AudioContext is not supported in this browser');
        }
        const audioCtx = new AudioContextClass({ sampleRate: 16000 });
        audioContextRef.current = audioCtx;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        let url = `${protocol}//${host}/api/v1/ws/voice`;
        if (typeof sessionId === 'string' && sessionId.trim().length > 0) {
          url += `?session_id=${sessionId}`;
        }

        const ws = new WebSocket(url);
        wsRef.current = ws;
        ws.binaryType = 'arraybuffer';

        ws.onopen = async () => {
          setState((prev) => ({ ...prev, isConnected: true, isConnecting: false }));

          try {
            const stream = await navigator.mediaDevices.getUserMedia({
              audio: {
                channelCount: 1,
                sampleRate: 16000,
                echoCancellation: true,
                noiseSuppression: true,
              },
            });
            mediaStreamRef.current = stream;

            const source = audioCtx.createMediaStreamSource(stream);
            const processor = audioCtx.createScriptProcessor(4096, 1, 1);
            processorNodeRef.current = processor;

            processor.onaudioprocess = (event) => {
              const inputData = event.inputBuffer.getChannelData(0);
              const pcmData = new Int16Array(inputData.length);
              for (let index = 0; index < inputData.length; index += 1) {
                const val = inputData[index];
                if (typeof val === 'number') {
                  pcmData[index] = Math.max(-32768, Math.min(32767, val * 32768));
                }
              }

              if (ws.readyState === WebSocket.OPEN) {
                ws.send(pcmData.buffer);
              }
            };

            source.connect(processor);
            processor.connect(audioCtx.destination);
          } catch {
            endSession();
          }
        };

        ws.onmessage = (event) => {
          if (event.data instanceof ArrayBuffer) {
            handleIncomingAudioChunkRef.current(event.data);
          } else {
            const data = JSON.parse(event.data) as VoiceMessage;
            switch (data.type) {
              case 'session_started':
                break;
              case 'status':
                if (typeof data.status === 'string') {
                  setState((prev) => ({
                    ...prev,
                    status: data.status as VoiceSessionState['status'],
                  }));
                }
                break;
              case 'partial_transcript':
                if (typeof data.text === 'string') {
                  setState((prev) => ({ ...prev, transcript: data.text as string }));
                }
                break;
              case 'response':
                if (typeof data.text === 'string') {
                  setState((prev) => ({
                    ...prev,
                    status: 'speaking',
                    transcript: data.text as string,
                  }));
                }
                if (typeof data.navigate_to === 'string' && data.navigate_to.trim().length > 0) {
                  window.dispatchEvent(
                    new CustomEvent('agent-navigate', {
                      detail: {
                        path: data.navigate_to,
                        label:
                          typeof data.navigate_label === 'string' &&
                          data.navigate_label.trim().length > 0
                            ? data.navigate_label
                            : 'Navigating...',
                      },
                    })
                  );
                }
                break;
              case 'stop_playback':
                stopAllAudioPlayback();
                setState((prev) => ({ ...prev, status: 'idle' }));
                break;
              case 'playback_ended':
                setState((prev) => ({ ...prev, status: 'idle' }));
                break;
              case 'permission_request':
                setState((prev) => ({
                  ...prev,
                  status: 'waiting_permission',
                  permissionRequest: {
                    action:
                      typeof data.action === 'string' && data.action.trim().length > 0
                        ? data.action
                        : 'unknown',
                    summary: typeof data.summary === 'string' ? data.summary : '',
                    payload: data.payload ?? null,
                  },
                }));
                break;
              default:
                break;
            }
          }
        };

        ws.onclose = (event) => {
          if (!event.wasClean) {
            setState((prev) => ({ ...prev, error: 'Voice server connection lost unexpectedly.' }));
            endSession(false);
          } else {
            endSession(true);
          }
        };

        ws.onerror = () => {
          setState((prev) => ({
            ...prev,
            error:
              'Failed to connect to the voice server. Please verify if the backend is running.',
          }));
          endSession(false);
        };
      } catch {
        endSession();
      }
    },
    [endSession, stopAllAudioPlayback]
  );

  function handleIncomingAudioChunk(buffer: ArrayBuffer) {
    const audioCtx = audioContextRef.current;
    if (!audioCtx) return;

    const int16Array = new Int16Array(buffer);
    const float32Array = new Float32Array(int16Array.length);
    for (let index = 0; index < int16Array.length; index += 1) {
      const val = int16Array[index];
      if (typeof val === 'number') {
        float32Array[index] = val / 32768.0;
      }
    }

    audioQueueRef.current.push(float32Array);
    playNextQueueChunk();
  }

  handleIncomingAudioChunkRef.current = handleIncomingAudioChunk;

  const playNextQueueChunk = () => {
    const audioCtx = audioContextRef.current;
    if (!audioCtx || isPlayingRef.current || audioQueueRef.current.length === 0) return;

    isPlayingRef.current = true;
    const chunk = audioQueueRef.current.shift();
    if (!chunk) {
      isPlayingRef.current = false;
      return;
    }

    const audioBuffer = audioCtx.createBuffer(1, chunk.length, 16000);
    audioBuffer.getChannelData(0).set(chunk);

    const sourceNode = audioCtx.createBufferSource();
    sourceNode.buffer = audioBuffer;
    sourceNode.connect(audioCtx.destination);

    audioSourcesRef.current.push(sourceNode);

    let playTime = nextPlayTimeRef.current;
    const now = audioCtx.currentTime;

    if (playTime < now) {
      playTime = now + 0.05;
    }

    sourceNode.start(playTime);
    nextPlayTimeRef.current = playTime + audioBuffer.duration;

    sourceNode.onended = () => {
      audioSourcesRef.current = audioSourcesRef.current.filter((src) => src !== sourceNode);
      isPlayingRef.current = false;
      playNextQueueChunk();
    };
  };

  const sendPermissionResponse = (approved: boolean) => {
    if (
      wsRef.current &&
      wsRef.current.readyState === WebSocket.OPEN &&
      state.permissionRequest !== null
    ) {
      wsRef.current.send(
        JSON.stringify({
          type: 'permission_response',
          approved,
          action: state.permissionRequest.action,
          payload: state.permissionRequest.payload,
        })
      );
      setState((prev) => ({ ...prev, permissionRequest: null, status: 'idle' }));
    }
  };

  useEffect(() => {
    return () => {
      endSession();
    };
  }, [endSession]);

  return (
    <VoiceSessionContext.Provider
      value={{
        state,
        startSession,
        endSession,
        sendPermissionResponse,
      }}
    >
      {children}
    </VoiceSessionContext.Provider>
  );
};
