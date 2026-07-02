import React, { createContext, useContext, useEffect, useRef, useState } from 'react';

export interface VoiceSessionState {
  status: 'idle' | 'transcribing' | 'thinking' | 'speaking' | 'waiting_permission';
  transcript: string;
  isConnecting: boolean;
  isConnected: boolean;
  permissionRequest: {
    action: string;
    summary: string;
    payload: any;
  } | null;
}

interface VoiceSessionContextType {
  state: VoiceSessionState;
  startSession: (sessionId?: string) => Promise<void>;
  endSession: () => void;
  sendPermissionResponse: (approved: boolean) => void;
}

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
  });

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorNodeRef = useRef<ScriptProcessorNode | null>(null);
  
  // Audio playback queue variables
  const audioQueueRef = useRef<Float32Array[]>([]);
  const isPlayingRef = useRef<boolean>(false);
  const nextPlayTimeRef = useRef<number>(0);
  const audioSourcesRef = useRef<AudioBufferSourceNode[]>([]);

  const endSession = () => {
    logger('Ending voice session...');
    
    // Stop recording
    if (processorNodeRef.current) {
      processorNodeRef.current.disconnect();
      processorNodeRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }

    // Stop playback
    stopAllAudioPlayback();

    // Close WebSocket
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'end_session' }));
      }
      wsRef.current.close();
      wsRef.current = null;
    }

    // Clean up audio context
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    setState({
      status: 'idle',
      transcript: '',
      isConnecting: false,
      isConnected: false,
      permissionRequest: null,
    });
  };

  const stopAllAudioPlayback = () => {
    logger('Stopping all audio playback...');
    audioSourcesRef.current.forEach((src) => {
      try {
        src.stop();
      } catch (e) {
        // Already stopped
      }
    });
    audioSourcesRef.current = [];
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    nextPlayTimeRef.current = 0;
  };

  const startSession = async (sessionId?: string) => {
    if (wsRef.current) return; // Already active

    logger('Starting voice session...');
    setState((prev) => ({ ...prev, isConnecting: true, transcript: '' }));

    try {
      // 1. Initialize Audio Context
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      const audioCtx = new AudioContextClass({ sampleRate: 16000 });
      audioContextRef.current = audioCtx;

      // 2. Connect to WebSocket
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = import.meta.env.DEV ? 'localhost:8000' : window.location.host;
      let url = `${protocol}//${host}/api/v1/ws/voice`;
      if (sessionId) {
        url += `?session_id=${sessionId}`;
      }

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.binaryType = 'arraybuffer';

      ws.onopen = async () => {
        logger('WebSocket connected. Requesting microphone permission...');
        setState((prev) => ({ ...prev, isConnected: true, isConnecting: false }));

        try {
          // Get Mic Access
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
            
            // Convert Float32Array to Int16Array PCM
            const pcmData = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
              pcmData[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
            }

            if (ws.readyState === WebSocket.OPEN) {
              ws.send(pcmData.buffer);
            }
          };

          source.connect(processor);
          processor.connect(audioCtx.destination);
          logger('Microphone streaming active.');
        } catch (err) {
          logger('Microphone access denied:', err);
          endSession();
        }
      };

      ws.onmessage = async (event) => {
        if (event.data instanceof ArrayBuffer) {
          // Binary audio chunk received from server
          handleIncomingAudioChunk(event.data);
        } else {
          // Control or transcript JSON message
          const data = JSON.parse(event.data);
          logger('WebSocket event:', data);

          switch (data.type) {
            case 'session_started':
              logger('Voice session ID confirmed:', data.session_id);
              break;
            case 'status':
              setState((prev) => ({ ...prev, status: data.status }));
              break;
            case 'partial_transcript':
              setState((prev) => ({ ...prev, transcript: data.text }));
              break;
            case 'response':
              setState((prev) => ({ ...prev, status: 'speaking', transcript: data.text }));
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
                  action: data.action,
                  summary: data.summary,
                  payload: data.payload,
                },
              }));
              break;
          }
        }
      };

      ws.onclose = () => {
        logger('WebSocket closed.');
        endSession();
      };

      ws.onerror = (err) => {
        logger('WebSocket error:', err);
        endSession();
      };

    } catch (e) {
      logger('Failed to initialize voice session:', e);
      endSession();
    }
  };

  const handleIncomingAudioChunk = (buffer: ArrayBuffer) => {
    const audioCtx = audioContextRef.current;
    if (!audioCtx) return;

    // Convert Int16 PCM array to Float32 array
    const int16Array = new Int16Array(buffer);
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0;
    }

    // Push into queue
    audioQueueRef.current.push(float32Array);
    
    // Trigger queue player
    playNextQueueChunk();
  };

  const playNextQueueChunk = () => {
    const audioCtx = audioContextRef.current;
    if (!audioCtx || isPlayingRef.current || audioQueueRef.current.length === 0) return;

    isPlayingRef.current = true;
    const chunk = audioQueueRef.current.shift()!;

    // Create an AudioBuffer
    const audioBuffer = audioCtx.createBuffer(1, chunk.length, 16000);
    audioBuffer.getChannelData(0).set(chunk);

    // Create a SourceNode
    const sourceNode = audioCtx.createBufferSource();
    sourceNode.buffer = audioBuffer;
    sourceNode.connect(audioCtx.destination);

    audioSourcesRef.current.push(sourceNode);

    // Schedule play time to avoid overlaps and gaps
    let playTime = nextPlayTimeRef.current;
    const now = audioCtx.currentTime;

    if (playTime < now) {
      playTime = now + 0.05; // Short buffering delay
    }

    sourceNode.start(playTime);
    
    // Save next chunk expected start time
    nextPlayTimeRef.current = playTime + audioBuffer.duration;

    sourceNode.onended = () => {
      // Remove from source registry
      audioSourcesRef.current = audioSourcesRef.current.filter((src) => src !== sourceNode);
      isPlayingRef.current = false;
      // Loop
      playNextQueueChunk();
    };
  };

  const sendPermissionResponse = (approved: boolean) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && state.permissionRequest) {
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

  const logger = (...args: any[]) => {
    console.log('[VoiceSession]', ...args);
  };

  // Clean up on component unmount
  useEffect(() => {
    return () => {
      endSession();
    };
  }, []);

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
