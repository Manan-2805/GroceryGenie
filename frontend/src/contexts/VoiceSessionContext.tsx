import { useCallback, useEffect, useRef, useState } from 'react';

import type { AssistantEvent } from '../services/assistant';

type Status = 'idle' | 'connecting' | 'listening' | 'transcribing' | 'thinking' | 'speaking';

type VoiceCallbacks = {
  session: (id: string) => void;
  speech: (text: string) => void;
  event: (event: AssistantEvent) => void;
};

type VoiceConnection = {
  audio: AudioContext;
  stream: MediaStream | null;
  worklet: AudioWorkletNode | null;
  socket: WebSocket | null;
  sampleRate: number;
  acceptInput: boolean;
  playbackComplete: boolean;
  audioEnd: number;
  sources: Set<AudioBufferSourceNode>;
};

type WireMessage =
  | AssistantEvent
  | {
      type:
        | 'voice_error'
        | 'session_started'
        | 'audio_format'
        | 'playback_ended'
        | 'stop_playback'
        | 'partial_transcript'
        | 'status';
      text?: string;
      session_id?: string;
      sample_rate?: number;
      status?: Status;
    };

function stopAudio(connection: VoiceConnection) {
  connection.sources.forEach((source) => {
    source.onended = null;
    source.stop();
    source.disconnect();
  });
  connection.sources.clear();
  connection.audioEnd = 0;
  connection.playbackComplete = false;
}

export function useVoiceSession(callbacks: VoiceCallbacks) {
  const latest = useRef(callbacks);
  latest.current = callbacks;
  const connectionRef = useRef<VoiceConnection | null>(null);
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState('');

  const endSession = useCallback(() => {
    const connection = connectionRef.current;
    connectionRef.current = null;
    if (connection) {
      stopAudio(connection);
      connection.worklet?.disconnect();
      connection.stream?.getTracks().forEach((track) => track.stop());
      connection.socket?.close();
      void connection.audio.close().catch(() => undefined);
    }
    setStatus('idle');
  }, []);

  useEffect(() => endSession, [endSession]);

  const startSession = async (sessionId: string | null) => {
    if (connectionRef.current) return;
    setError('');
    setStatus('connecting');
    if (
      typeof navigator.mediaDevices?.getUserMedia !== 'function' ||
      typeof window.AudioContext !== 'function'
    ) {
      setError('Voice requires microphone access in a secure browser context.');
      setStatus('idle');
      return;
    }
    const connection: VoiceConnection = {
      audio: new AudioContext({ sampleRate: 16000 }),
      stream: null,
      worklet: null,
      socket: null,
      sampleRate: 16000,
      acceptInput: false,
      playbackComplete: false,
      audioEnd: 0,
      sources: new Set(),
    };
    connectionRef.current = connection;
    const current = () => connectionRef.current === connection;
    try {
      await connection.audio.resume();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (!current()) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      connection.stream = stream;
      await connection.audio.audioWorklet.addModule('/voice-capture.js');
      if (!current()) return;
      const input = connection.audio.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(connection.audio, 'voice-capture');
      connection.worklet = worklet;
      input.connect(worklet);
      worklet.connect(connection.audio.destination);
      const url = new URL('/api/v1/ws/voice', window.location.href);
      url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      if (sessionId !== null) url.searchParams.set('session_id', sessionId);
      const socket = new WebSocket(url);
      socket.binaryType = 'arraybuffer';
      connection.socket = socket;
      worklet.port.onmessage = ({ data }: MessageEvent<ArrayBuffer>) => {
        if (
          current() &&
          connection.acceptInput &&
          socket.readyState === WebSocket.OPEN &&
          socket.bufferedAmount < 32768
        ) {
          socket.send(data);
        }
      };
      const resumeListening = () => {
        if (
          !current() ||
          !connection.playbackComplete ||
          connection.sources.size > 0 ||
          socket.readyState !== WebSocket.OPEN
        )
          return;
        connection.playbackComplete = false;
        socket.send(JSON.stringify({ type: 'playback_complete' }));
        connection.acceptInput = true;
        setStatus('listening');
      };
      socket.onmessage = ({ data }: MessageEvent<unknown>) => {
        if (!current()) return;
        if (data instanceof ArrayBuffer && data.byteLength > 0 && data.byteLength % 2 === 0) {
          const pcm = new Int16Array(data);
          const buffer = connection.audio.createBuffer(1, pcm.length, connection.sampleRate);
          buffer.getChannelData(0).set(Float32Array.from(pcm, (sample) => sample / 32768));
          const playback = connection.audio.createBufferSource();
          playback.buffer = buffer;
          playback.connect(connection.audio.destination);
          const start = Math.max(connection.audio.currentTime + 0.015, connection.audioEnd);
          connection.audioEnd = start + buffer.duration;
          connection.sources.add(playback);
          playback.onended = () => {
            playback.disconnect();
            connection.sources.delete(playback);
            resumeListening();
          };
          playback.start(start);
          setStatus('speaking');
          return;
        }
        if (typeof data !== 'string') return;
        const frame = JSON.parse(data) as WireMessage;
        switch (frame.type) {
          case 'session_started':
            if (typeof frame.session_id === 'string') latest.current.session(frame.session_id);
            break;
          case 'status':
            connection.acceptInput = false;
            if (frame.status !== undefined) setStatus(frame.status);
            break;
          case 'partial_transcript':
            if (typeof frame.text === 'string' && frame.text.length > 0)
              latest.current.speech(frame.text);
            break;
          case 'response':
          case 'permission_request':
            latest.current.event(frame);
            break;
          case 'audio_format':
            if (
              typeof frame.sample_rate === 'number' &&
              frame.sample_rate >= 8000 &&
              frame.sample_rate <= 48000
            ) {
              connection.sampleRate = frame.sample_rate;
            }
            break;
          case 'playback_ended':
            connection.playbackComplete = true;
            resumeListening();
            break;
          case 'stop_playback':
            stopAudio(connection);
            connection.acceptInput = true;
            setStatus('listening');
            break;
          case 'voice_error':
            setError(frame.text ?? 'Voice is unavailable. Continue in Text Mode.');
            endSession();
            break;
        }
      };
      socket.onclose = () => {
        if (!current()) return;
        setError('Voice ended. Start it again or continue in Text Mode.');
        endSession();
      };
    } catch {
      if (current()) {
        setError('Microphone or audio setup failed. Check browser permissions or use Text Mode.');
        endSession();
      }
    }
  };

  function send(frame: object) {
    const connection = connectionRef.current;
    if (connection?.socket?.readyState !== WebSocket.OPEN) return;
    connection.socket.send(JSON.stringify(frame));
  }

  return {
    status,
    error,
    startSession,
    endSession,
    interrupt: () => send({ type: 'interrupt' }),
    confirm: (id: string, approved: boolean) =>
      send({ type: 'permission_response', confirmation_id: id, approved }),
  };
}
