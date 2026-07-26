import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';

export type VoiceSessionState = {
  status: 'idle' | 'transcribing' | 'thinking' | 'speaking' | 'waiting_permission';
  transcript: string;
  sttTiming: number | null; // STT transcription time in seconds
  isConnecting: boolean;
  isConnected: boolean;
  permissionRequest: {
    action: string;
    summary: string;
    payload: unknown;
  } | null;
  lastToolResult: Record<string, unknown> | null;
  error: string | null;
  audioLevel: number; // 0-1 for waveform visualization
  optionsRequest: {
    text: string;
    options: Array<{
      label: string;
      value: string;
      description?: string;
      actions?: Array<{ label: string; value: string }>;
    }>;
    freeInputAllowed: boolean;
    cardVariant?: string;
  } | null;
  roleSwitchRequest: {
    text: string;
    neededRole: string;
    originalTool: string;
    options: Array<{ label: string; value: string; description?: string }>;
  } | null;
};

type VoiceSessionContextType = {
  state: VoiceSessionState;
  startSession: (sessionId?: string) => Promise<void>;
  endSession: (clearError?: boolean) => void;
  sendPermissionResponse: (approved: boolean) => void;
  sendTextMessage: (text: string) => void;
};

type VoiceMessage = {
  type?: string;
  action?: string;
  summary?: string;
  payload?: unknown;
  result?: Record<string, unknown>;
  status?: VoiceSessionState['status'];
  text?: string;
  timing?: number;
  navigate_to?: string;
  navigate_label?: string;
  session_id?: string;
  options?: Array<{
    label: string;
    value: string;
    description?: string;
    actions?: Array<{ label: string; value: string }>;
  }>;
  free_input_allowed?: boolean;
  needed_role?: string;
  original_tool?: string;
  card_variant?: string;
};

const VoiceSessionContext = createContext<VoiceSessionContextType | null>(null);

export const useVoiceSession = () => {
  const context = useContext(VoiceSessionContext);
  if (!context) {
    throw new Error('useVoiceSession must be used within a VoiceSessionProvider');
  }
  return context;
};

const MAX_RECONNECT_ATTEMPTS = 3;
const RECONNECT_BASE_DELAY = 1000;

export const VoiceSessionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<VoiceSessionState>({
    status: 'idle',
    transcript: '',
    sttTiming: null,
    isConnecting: false,
    isConnected: false,
    permissionRequest: null,
    lastToolResult: null,
    error: null,
    audioLevel: 0,
    optionsRequest: null,
    roleSwitchRequest: null,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorNodeRef = useRef<ScriptProcessorNode | null>(null);
  const audioQueueRef = useRef<Float32Array[]>([]);
  const isPlayingRef = useRef<boolean>(false);
  const nextPlayTimeRef = useRef<number>(0);
  const audioSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const heartbeatIntervalRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const sessionIdRef = useRef<string | undefined>(undefined);
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

  const cleanupResources = useCallback(() => {
    if (processorNodeRef.current) {
      processorNodeRef.current.disconnect();
      processorNodeRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    stopAllAudioPlayback();
    if (heartbeatIntervalRef.current !== null) {
      window.clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }
  }, [stopAllAudioPlayback]);

  const endSession = useCallback(
    (clearError = true) => {
      cleanupResources();

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
        sttTiming: null,
        isConnecting: false,
        isConnected: false,
        permissionRequest: null,
        lastToolResult: null,
        error: clearError ? null : prev.error,
        audioLevel: 0,
        optionsRequest: null,
        roleSwitchRequest: null,
      }));
    },
    [cleanupResources]
  );

  const startSession = useCallback(
    async (sessionId?: string) => {
      if (wsRef.current) return;

      sessionIdRef.current = sessionId;
      reconnectAttemptsRef.current = 0;

      setState((prev) => ({
        ...prev,
        isConnecting: true,
        transcript: '',
        error: null,
        audioLevel: 0,
      }));

      const connect = async (): Promise<void> => {
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
            reconnectAttemptsRef.current = 0;

            // Start heartbeat
            heartbeatIntervalRef.current = window.setInterval(() => {
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'pong' }));
              }
            }, 25000);

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

                // AudioContext is usually 48000 Hz, backend expects 16000 Hz.
                const inputRate = audioCtx.sampleRate;
                const outputRate = 16000;
                const ratio = inputRate / outputRate;

                const outputLength = Math.floor(inputData.length / ratio);
                const pcmData = new Int16Array(outputLength);

                let sumSquares = 0;

                for (let i = 0; i < outputLength; i++) {
                  const srcIndex = Math.floor(i * ratio);
                  const sample = inputData[srcIndex] ?? 0;

                  sumSquares += sample * sample;

                  pcmData[i] = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)));
                }

                const rms = Math.sqrt(sumSquares / outputLength);
                const level = Math.min(1, rms * 5);

                setState((prev) => ({
                  ...prev,
                  audioLevel: level,
                }));

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
                    setState((prev) => ({
                      ...prev,
                      transcript: data.text as string,
                      sttTiming: typeof data.timing === 'number' ? data.timing : null,
                      optionsRequest: null,
                      roleSwitchRequest: null,
                    }));
                  }
                  break;
                case 'options_request':
                  if (typeof data.text === 'string') {
                    setState((prev) => ({
                      ...prev,
                      status: 'speaking',
                      transcript: data.text as string,
                      optionsRequest: {
                        text: data.text as string,
                        options: Array.isArray(data.options) ? data.options : [],
                        freeInputAllowed: data.free_input_allowed !== false,
                        ...(typeof data.card_variant === 'string'
                          ? { cardVariant: data.card_variant }
                          : {}),
                      },
                    }));
                  }
                  break;
                case 'toggle_theme':
                  // Pure client-side toggle — dispatch the same event text chat uses
                  window.dispatchEvent(new CustomEvent('agent-toggle-theme'));
                  break;
                case 'role_switch_request':
                  if (typeof data.text === 'string') {
                    setState((prev) => ({
                      ...prev,
                      status: 'speaking',
                      transcript: data.text as string,
                      roleSwitchRequest: {
                        text: data.text as string,
                        neededRole: (data.needed_role as string) || 'seller',
                        originalTool: (data.original_tool as string) || '',
                        options: Array.isArray(data.options) ? data.options : [],
                      },
                    }));
                  }
                  break;
                case 'tool_result':
                  if (typeof data.result === 'object' && data.result !== null) {
                    setState((prev) => ({
                      ...prev,
                      lastToolResult: data.result as Record<string, unknown>,
                    }));
                  }
                  break;
                case 'response':
                  if (typeof data.text === 'string') {
                    setState((prev) => ({
                      ...prev,
                      status: 'speaking',
                      transcript: data.text as string,
                      optionsRequest: null,
                      roleSwitchRequest: null,
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
                case 'ping':
                  if (ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({ type: 'pong' }));
                  }
                  break;
                default:
                  break;
              }
            }
          };

          ws.onclose = async (event) => {
            cleanupResources();
            if (!event.wasClean && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
              reconnectAttemptsRef.current += 1;
              const delay = RECONNECT_BASE_DELAY * reconnectAttemptsRef.current;
              setState((prev) => ({ ...prev, isConnecting: true }));
              await new Promise<void>((resolve) => {
                window.setTimeout(resolve, delay);
              });
              await connect();
            } else if (!event.wasClean) {
              setState((prev) => ({
                ...prev,
                error: 'Voice server connection lost unexpectedly.',
              }));
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
      };

      await connect();
    },
    [endSession, cleanupResources, stopAllAudioPlayback]
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

  const sendTextMessage = (text: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'free_input',
          text,
        })
      );
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
        sendTextMessage,
      }}
    >
      {children}
    </VoiceSessionContext.Provider>
  );
};
