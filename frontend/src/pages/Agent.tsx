import {
  MessageSquare,
  Mic,
  Send,
  ShieldAlert,
  ArrowLeft,
  ShoppingCart,
  MapPin,
  User,
} from 'lucide-react';
import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { useVoiceSession } from '../contexts/VoiceSessionContext';
import { api, authService } from '../services/api';
import { useUIStore } from '../store/uiStore';

type OptionAction = {
  label: string;
  value: string;
};

type OptionItem = {
  label: string;
  value: string;
  description?: string;
  actions?: OptionAction[];
};

type Message = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  type?:
    | 'text'
    | 'permission'
    | 'options'
    | 'order_detail'
    | 'fulfillment_queue'
    | 'inventory'
    | 'navigation'
    | 'action_card'
    | 'status'
    | 'role_switch';
  options?: OptionItem[];
  free_input_allowed?: boolean;
  navigate_to?: string;
  navigate_label?: string;
  action_data?: Record<string, unknown>;
  needed_role?: string;
  original_tool?: string;
  card_variant?: string;
};

type StreamEvent =
  | { type: 'delta'; text: string }
  | { type: 'status'; status: string }
  | { type: 'toggle_theme'; text: string }
  | {
      type: 'permission_request';
      summary: string;
      action: string;
      payload: Record<string, unknown>;
    }
  | {
      type: 'role_switch_request';
      text: string;
      summary: string;
      options: { label: string; value: string; description?: string }[];
      needed_role: string;
      original_tool: string;
      free_input_allowed: boolean;
    }
  | { type: 'navigate_to'; path: string; label: string }
  | {
      type: 'options_request';
      text: string;
      options: { label: string; value: string; description?: string }[];
      free_input_allowed: boolean;
      card_variant?: string;
    }
  | {
      type: 'response';
      text: string;
      options?: unknown[];
      free_input_allowed?: boolean;
    };

// eslint-disable-next-line @typescript-eslint/no-unused-vars
let _messageIdCounter = 0;
const nextId = () => {
  _messageIdCounter += 1;
  return `msg-${_messageIdCounter}-${Date.now()}`;
};

export const Agent: React.FC = () => {
  const navigate = useNavigate();
  const { sessionId, setSessionId, clearSession, voiceOk, toggleTheme } = useUIStore();
  const {
    state: voiceState,
    startSession,
    endSession,
    sendPermissionResponse,
    sendTextMessage: sendVoiceMessage,
  } = useVoiceSession();

  const [mode, setMode] = useState<'select' | 'text' | 'voice'>('select');
  const [messages, setMessages] = useState<Message[]>([]);
  const [textInput, setTextInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [chatError, setChatError] = useState(false);
  const [processingPermission, setProcessingPermission] = useState(false);
  const [userName, setUserName] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Track the latest message ID for append-only operations across renders
  const latestAssistantMsgIdRef = useRef<string | null>(null);

  useEffect(() => {
    // Fetch user name for greeting
    authService
      .getMe()
      .then((data) => setUserName(data.name))
      .catch((e) => {
        console.error('Failed to fetch user info:', e);
      });
  }, []);

  // Load history when sessionId changes (mount or after clearSession + new session).
  // Only auto-restores to text mode if no manual mode override has happened.
  useEffect(() => {
    if (!sessionId) return;
    api
      .get<{ messages: { role: string; content: string }[]; count: number }>(`/chat/history`, {
        params: { session_id: sessionId, limit: 20 },
      })
      .then((res) => {
        const data = res.data;
        if (!data || data.count < 2) return;
        const loadedMessages: Message[] = data.messages.map((m) => ({
          id: nextId(),
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content,
          type: 'text' as const,
        }));
        // Use functional updater so we don't overwrite a manual mode change
        setMode((prev) => (prev === 'select' ? 'text' : prev));
        setMessages(loadedMessages);
      })
      .catch(() => {
        // History load failed — start fresh, don't block the user
      });
  }, [sessionId]);

  // Listen for theme-toggle events dispatched by the SSE handler
  useEffect(() => {
    const handler = () => toggleTheme();
    window.addEventListener('agent-toggle-theme', handler);
    return () => window.removeEventListener('agent-toggle-theme', handler);
  }, [toggleTheme]);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, voiceState.transcript, voiceState.status]);

  const handleStartTextChat = () => {
    setMode('text');
    setChatError(false);
    // Clear any existing session so a fresh one is created on first send
    clearSession();
    setMessages([
      {
        id: nextId(),
        role: 'assistant',
        content: `Hi ${userName !== '' ? userName : 'there'}! I'm your GroceryGenie assistant. I can help you find products, manage your cart, check orders, manage addresses, and more. How can I help?`,
      },
    ]);
    window.setTimeout(() => {
      inputRef.current?.focus();
    }, 100);
  };

  const handleStartVoiceChat = async () => {
    setMode('voice');
    // Reuse existing session if present; create new one otherwise
    const voiceSessionId = sessionId ?? window.crypto.randomUUID();
    setSessionId(voiceSessionId);
    await startSession(voiceSessionId);
  };

  const handleBackToSelect = () => {
    if (mode === 'voice') {
      endSession();
    }
    clearSession();
    setMode('select');
    setMessages([]);
  };

  const sendTextMessage = async (
    msgText: string,
    approvedAction?: string,
    approvedPayload?: Record<string, unknown>
  ) => {
    if (msgText.trim().length === 0 && approvedAction === undefined) return;

    if (approvedAction === undefined) {
      setMessages((prev) => [...prev, { id: nextId(), role: 'user', content: msgText }]);
      setTextInput('');
    }

    setIsSending(true);
    // Reset the assistant message ID tracker for this new request
    latestAssistantMsgIdRef.current = null;

    // Cancel previous request if any
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch('/api/v1/chat/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        signal: abortControllerRef.current.signal,
        body: JSON.stringify({
          message: msgText,
          session_id: sessionId,
          approved_action: approvedAction,
          approved_payload: approvedPayload,
        }),
      });

      if (!response.ok) {
        throw new Error('Not authenticated or server unavailable');
      }

      if (!response.body) throw new Error('No response stream body');

      // Persist session_id from response header (set by backend on session creation)
      const returnedSessionId = response.headers.get('X-Session-ID');
      if (
        returnedSessionId !== null &&
        returnedSessionId !== undefined &&
        returnedSessionId !== sessionId
      ) {
        setSessionId(returnedSessionId);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantResponse = '';
      // SSE line buffer — accumulates raw bytes across chunk boundaries so
      // a data: line split across two reads is never silently dropped.
      let sseBuffer = '';

      const handleSseEvent = (dataStr: string) => {
        try {
          const data = JSON.parse(dataStr) as Partial<StreamEvent> & Record<string, unknown>;

          if (data.type === 'status' && typeof data.status === 'string') {
            const statusContent = data.status ?? '';
            setMessages((prev) => {
              const updated = [...prev];
              const lastMsg = updated[updated.length - 1];
              if (lastMsg && lastMsg.type === 'status') {
                updated[updated.length - 1] = { ...lastMsg, content: statusContent };
              } else {
                updated.push({
                  id: nextId(),
                  role: 'system',
                  content: statusContent,
                  type: 'status' as const,
                });
              }
              return updated;
            });
            window.setTimeout(() => {
              setMessages((prev) => prev.filter((m) => m.type !== 'status'));
            }, 3000);
          } else if (data.type === 'delta' && typeof data.text === 'string') {
            assistantResponse += data.text;
            setMessages((prev) => {
              const updated = [...prev];
              const lastMsg = updated[updated.length - 1];
              if (lastMsg && lastMsg.role === 'assistant' && lastMsg.type === 'text') {
                updated[updated.length - 1] = { ...lastMsg, content: assistantResponse };
              } else {
                updated.push({
                  id: nextId(),
                  role: 'assistant',
                  content: assistantResponse,
                  type: 'text',
                });
              }
              return updated;
            });
          } else if (data.type === 'response' && typeof data.text === 'string') {
            // Non-streaming response from backend (e.g. "No products found", slot-fill questions, etc.)
            const responseText = data.text;
            setMessages((prev) => {
              const updated = [...prev];
              const lastMsg = updated[updated.length - 1];
              if (lastMsg && lastMsg.role === 'assistant' && lastMsg.type === 'text' && lastMsg.content === '') {
                // Replace empty placeholder with the actual response text
                updated[updated.length - 1] = { ...lastMsg, content: responseText };
              } else {
                updated.push({
                  id: nextId(),
                  role: 'assistant',
                  content: responseText,
                  type: 'text',
                });
              }
              return updated;
            });
          } else if (data.type === 'toggle_theme') {
            // Pure client-side — toggle theme and show confirmation
            window.dispatchEvent(new CustomEvent('agent-toggle-theme'));
            setMessages((prev) => [
              ...prev,
              {
                id: nextId(),
                role: 'assistant',
                content: typeof data.text === 'string' ? data.text : 'Theme toggled.',
                type: 'text',
              },
            ]);
          } else if (
            data.type === 'permission_request' &&
            typeof data.summary === 'string' &&
            data.summary.length > 0
          ) {
            const summary = String(data.summary);
            setMessages((prev) => [
              ...prev.filter((m) => m.content !== ''),
              {
                id: nextId(),
                role: 'assistant',
                content: summary,
                type: 'permission',
                action_data: {
                  action: data.action,
                  summary: data.summary,
                  payload: data.payload,
                },
              },
            ]);
          } else if (data.type === 'role_switch_request') {
            const text = typeof data.text === 'string' ? data.text : '';
            const summary = typeof data.summary === 'string' ? data.summary : '';
            const neededRole = typeof data.needed_role === 'string' ? data.needed_role : 'seller';
            const originalTool = typeof data.original_tool === 'string' ? data.original_tool : '';
            const roleOptions: OptionItem[] = Array.isArray(data.options)
              ? data.options.filter(
                  (opt: unknown): opt is { label: string; value: string; description?: string } =>
                    typeof opt === 'object' && opt !== null && 'label' in opt && 'value' in opt
                )
              : [];
            setMessages((prev) => [
              ...prev,
              {
                id: nextId(),
                role: 'assistant',
                content: text || summary,
                type: 'role_switch',
                options: roleOptions,
                free_input_allowed: false,
                needed_role: neededRole,
                original_tool: originalTool,
              },
            ]);
          } else if (data.type === 'options_request') {
            // card_variant lets the renderer pick the right layout (fulfillment_queue, inventory, etc.)
            const cardVariant =
              typeof data.card_variant === 'string' ? data.card_variant : undefined;
            const msgType: Message['type'] =
              cardVariant === 'fulfillment_queue'
                ? 'fulfillment_queue'
                : cardVariant === 'inventory'
                  ? 'inventory'
                  : cardVariant === 'order_detail'
                    ? 'order_detail'
                    : 'options';
            setMessages((prev) => [
              ...prev,
              {
                id: nextId(),
                role: 'assistant',
                content: typeof data.text === 'string' ? data.text : '',
                type: msgType,
                options: Array.isArray(data.options)
                  ? data.options.filter(
                      (option): option is { label: string; value: string; description?: string } =>
                        typeof option === 'object' &&
                        option !== null &&
                        'label' in option &&
                        'value' in option
                    )
                  : [],
                free_input_allowed: data.free_input_allowed !== false,
                ...(cardVariant !== undefined ? { card_variant: cardVariant } : {}),
              },
            ]);
          } else if (data.type === 'navigate_to' && typeof data.path === 'string') {
            window.dispatchEvent(
              new CustomEvent('agent-navigate', {
                detail: {
                  path: data.path,
                  label:
                    typeof data.label === 'string' && data.label.length > 0
                      ? data.label
                      : 'Navigating...',
                },
              })
            );
          }
        } catch {
          // JSON parse error on this event — log in dev, skip silently in prod
          if (import.meta.env.DEV) {
            console.warn('[SSE] Failed to parse event data:', dataStr.slice(0, 200));
          }
        }
      };

      // Chunk-buffering read loop — never splits a data: line across iterations
      let hasMoreChunks = true;
      while (hasMoreChunks) {
        const { value, done } = await reader.read();
        if (done) {
          hasMoreChunks = false;
          // Flush any remaining buffer content
          if (sseBuffer.trim()) {
            const remaining = sseBuffer.trim();
            if (remaining.startsWith('data:')) {
              handleSseEvent(remaining.slice(5).trim());
            }
          }
          continue;
        }

        // Append new chunk to rolling buffer
        sseBuffer += decoder.decode(value, { stream: true });

        // Extract and process every complete line (terminated by \n)
        let newlineIdx: number;
        while ((newlineIdx = sseBuffer.indexOf('\n')) !== -1) {
          const line = sseBuffer.slice(0, newlineIdx).trimEnd();
          sseBuffer = sseBuffer.slice(newlineIdx + 1);

          if (line.startsWith('data:')) {
            handleSseEvent(line.slice(5).trim());
          }
          // Ignore event:, id:, comment lines — not used by our SSE server
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name === 'AbortError') return;
      console.error(e);
      setChatError(true);
      setMessages((prev) => [
        ...prev.filter((m) => m.content !== ''),
        {
          id: nextId(),
          role: 'assistant',
          content:
            'Error: Failed to connect. Please verify you are logged in and the server is running.',
          type: 'text',
        },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleTextSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (chatError || textInput.length > 500 || textInput.trim().length === 0) return;
    void sendTextMessage(textInput);
  };

  const [selectedOptionByMsgId, setSelectedOptionByMsgId] = useState<Record<string, string>>({});

  const handleOptionSelect = (msgId: string, optionValue: string) => {
    // Check if message options are already consumed
    if (selectedOptionByMsgId[msgId] != null && selectedOptionByMsgId[msgId] !== '') return;

    setSelectedOptionByMsgId((prev) => ({
      ...prev,
      [msgId]: optionValue,
    }));

    // Send option as a direct text message (sendTextMessage handles adding the user message once)
    void sendTextMessage(optionValue);
  };

  const handlePermissionResponse = (approved: boolean, actionData?: Record<string, unknown>) => {
    if (processingPermission) return;
    setProcessingPermission(true);

    if (mode === 'voice') {
      sendPermissionResponse(approved);
    } else if (actionData) {
      void sendTextMessage(
        `Approved: ${actionData.action as string}`,
        String(actionData.action),
        (actionData.payload ?? {}) as Record<string, unknown>
      );
    }
  };

  const handleBackToHome = () => {
    if (mode === 'voice') {
      endSession();
    }
    void navigate('/');
  };

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col glass-panel overflow-hidden">
      {/* Header */}
      <div className="p-4 bg-accent text-white flex items-center justify-between shrink-0 rounded-t-2xl">
        <div className="flex items-center gap-3">
          <button
            onClick={handleBackToHome}
            className="hover:bg-white/20 p-1.5 rounded-full transition"
          >
            <ArrowLeft size={20} />
          </button>
          <div className="w-9 h-9 rounded-full bg-white/20 flex items-center justify-center font-bold text-sm">
            GG
          </div>
          <div>
            <h3 className="font-semibold text-sm">GroceryGenie Assistant</h3>
            <p className="text-[10px] text-white/80">
              {mode === 'voice' ? 'Voice Mode Active' : mode === 'text' ? 'Text Chat' : 'Ready'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {mode !== 'select' && (
            <button
              onClick={handleBackToSelect}
              className="hover:bg-white/20 p-1.5 rounded-full transition"
              title="Switch mode"
            >
              <MessageSquare size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Mode Selection */}
      {mode === 'select' && (
        <div className="flex-1 flex flex-col">
          {!voiceOk && (
            <div className="w-full p-3 bg-amber-500/10 border-b border-amber-500/20 text-amber-600 dark:text-amber-400 text-xs font-semibold text-center flex items-center justify-center gap-1.5">
              <ShieldAlert size={14} className="shrink-0" />
              <span>Voice services are currently unavailable.</span>
            </div>
          )}

          <div className="flex-1 p-8 flex flex-col justify-center items-center gap-8 max-w-lg mx-auto w-full">
            <div className="text-center">
              <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-200">
                Welcome{userName !== '' ? `, ${userName}` : ''}!
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                I'm your AI shopping assistant. Choose how you'd like to chat:
              </p>
            </div>

            <div className="flex flex-col gap-4 w-full">
              {/* Text Chat Option */}
              <button
                onClick={handleStartTextChat}
                className="w-full p-6 flex items-center gap-4 border-2 border-accent-border hover:border-accent rounded-2xl hover:bg-accent-bg dark:hover:bg-accent-bg transition-all group"
              >
                <div className="w-14 h-14 rounded-xl bg-accent-bg dark:bg-accent-bg flex items-center justify-center group-hover:scale-105 transition">
                  <MessageSquare size={28} className="text-accent" />
                </div>
                <div className="text-left">
                  <span className="font-bold text-lg text-gray-800 dark:text-gray-200">
                    Text Chat
                  </span>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    Type your questions and get instant answers
                  </p>
                </div>
              </button>

              {/* Voice Chat Option */}
              <button
                onClick={voiceOk ? handleStartVoiceChat : undefined}
                disabled={!voiceOk}
                className={`w-full p-6 flex items-center gap-4 border-2 rounded-2xl transition-all group ${
                  voiceOk
                    ? 'border-accent-border hover:border-accent hover:bg-accent-bg dark:hover:bg-accent-bg'
                    : 'border-gray-200 dark:border-gray-800 opacity-40 cursor-not-allowed'
                }`}
              >
                <div className="w-14 h-14 rounded-xl bg-accent-bg dark:bg-accent-bg flex items-center justify-center group-hover:scale-105 transition">
                  <Mic size={28} className="text-accent" />
                </div>
                <div className="text-left">
                  <span className="font-bold text-lg text-gray-800 dark:text-gray-200">
                    {voiceOk ? 'Voice Chat' : 'Voice Disabled'}
                  </span>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    {voiceOk ? "Speak naturally and I'll respond" : 'Voice service unavailable'}
                  </p>
                </div>
              </button>
            </div>

            {/* Quick action suggestions */}
            <div className="w-full">
              <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 mb-3 uppercase tracking-wider">
                Try asking me:
              </p>
              <div className="flex flex-wrap gap-2">
                {[
                  { icon: <ShoppingCart size={14} />, text: 'Add items to cart' },
                  { icon: <MapPin size={14} />, text: 'Find products' },
                  { icon: <User size={14} />, text: 'Check my orders' },
                ].map((suggestion, _) => (
                  <button
                    key={suggestion.text}
                    onClick={handleStartTextChat}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 dark:bg-gray-900 hover:bg-accent-bg dark:hover:bg-accent-bg rounded-full text-xs font-medium text-gray-600 dark:text-gray-400 transition border dark:border-gray-800"
                  >
                    {suggestion.icon}
                    {suggestion.text}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Text Chat Panel */}
      {mode === 'text' && (
        <>
          {/* Message List */}
          <div className="flex-1 p-4 overflow-y-auto space-y-3 flex flex-col bg-gray-50/50 dark:bg-gray-950/10">
            {messages.map((m) => {
              if (m.type === 'role_switch') {
                return (
                  <div key={m.id} className="max-w-[90%] self-center w-full">
                    <div className="p-4 border rounded-2xl border-accent-border dark:border-accent bg-accent-bg dark:bg-accent-bg">
                      <div className="flex items-center gap-2 text-accent dark:text-accent font-semibold mb-2 text-xs uppercase tracking-wider">
                        <ShieldAlert size={16} />
                        <span>Role Switch Required</span>
                      </div>
                      <p className="text-sm font-medium mb-4 text-gray-800 dark:text-gray-200">
                        {m.content}
                      </p>
                      {m.options && m.options.length > 0 && (
                        <div className="flex flex-col gap-2">
                          {m.options.map((opt) => {
                            const selectedValue = selectedOptionByMsgId[m.id];
                            const isSelected = selectedValue === opt.value;
                            const isCardConsumed = Boolean(selectedValue);

                            if (isCardConsumed && !isSelected) {
                              return (
                                <div
                                  key={opt.value}
                                  className="w-full px-4 py-2 border rounded-xl text-left bg-gray-50 dark:bg-gray-900 border-gray-200 dark:border-gray-800 opacity-40"
                                >
                                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                                    {opt.label}
                                  </span>
                                </div>
                              );
                            }

                            return (
                              <div key={opt.value} className="w-full">
                                {isSelected ? (
                                  <div className="w-full px-4 py-3 border rounded-xl text-left bg-accent-bg dark:bg-accent-bg border-accent-border dark:border-accent-border">
                                    <span className="text-[10px] text-accent dark:text-accent uppercase tracking-wider font-bold block mb-1">
                                      ✓ Selected
                                    </span>
                                    <span className="text-sm font-semibold text-heading dark:text-accent">
                                      {opt.label}
                                    </span>
                                  </div>
                                ) : (
                                  <button
                                    onClick={() => handleOptionSelect(m.id, opt.value)}
                                    disabled={isCardConsumed}
                                    className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-accent-bg dark:hover:bg-accent-bg border-gray-200 dark:border-gray-700"
                                  >
                                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                                      {opt.label}
                                    </span>
                                    {typeof opt.description === 'string' &&
                                      opt.description.length > 0 && (
                                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                          {opt.description}
                                        </p>
                                      )}
                                  </button>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                );
              }

              if (m.type === 'permission') {
                return (
                  <div key={m.id} className="max-w-[90%] self-center w-full">
                    <div className="p-4 border rounded-2xl border-amber-300 dark:border-amber-500 bg-amber-50 dark:bg-amber-950/20">
                      <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 font-semibold mb-2 text-xs uppercase tracking-wider">
                        <ShieldAlert size={16} />
                        <span>Permission Required</span>
                      </div>
                      <p className="text-sm font-medium mb-4 text-gray-800 dark:text-gray-200">
                        {m.content}
                      </p>
                      <div className="flex gap-3">
                        <button
                          onClick={() => handlePermissionResponse(true, m.action_data)}
                          disabled={processingPermission}
                          className="flex-1 px-4 py-2 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-300 disabled:cursor-not-allowed text-white rounded-xl text-xs font-bold transition"
                        >
                          {processingPermission ? 'Processing...' : 'Yes, proceed'}
                        </button>
                        <button
                          onClick={() => handlePermissionResponse(false)}
                          disabled={processingPermission}
                          className="flex-1 px-4 py-2 bg-gray-200 dark:bg-gray-800 hover:bg-gray-300 disabled:opacity-50 disabled:cursor-not-allowed text-gray-800 dark:text-gray-200 rounded-xl text-xs font-bold transition"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  </div>
                );
              }

              if (m.type === 'order_detail' && m.options) {
                // Order detail card — renders status timeline + items table + address
                return (
                  <div key={m.id} className="max-w-[95%] self-start w-full">
                    <div className="p-4 bg-gray-100 dark:bg-gray-900 rounded-2xl rounded-tl-none border dark:border-gray-800">
                      {/* Header */}
                      <p className="text-sm font-bold text-gray-800 dark:text-gray-200 mb-3 whitespace-pre-wrap">
                        {m.content}
                      </p>
                      {/* Action buttons on each item if any */}
                      {m.options.length > 0 && m.options[0]?.actions && (
                        <div className="flex gap-1.5 flex-wrap mt-2">
                          {m.options[0].actions.map((action) => (
                            <button
                              key={action.value}
                              onClick={() => handleOptionSelect(m.id, action.value)}
                              className="px-3 py-1.5 bg-accent-bg text-accent rounded-lg text-[11px] font-semibold transition hover:opacity-80"
                            >
                              {action.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              }

              if (m.type === 'fulfillment_queue' && m.options) {
                const isConsumed = Boolean(selectedOptionByMsgId[m.id]);
                return (
                  <div key={m.id} className="max-w-[95%] self-start w-full">
                    <div className="p-4 bg-gray-100 dark:bg-gray-900 rounded-2xl rounded-tl-none border dark:border-gray-800">
                      {/* Header */}
                      {m.content && (
                        <p className="text-sm font-bold text-gray-800 dark:text-gray-200 mb-3">
                          {m.content}
                        </p>
                      )}
                      <div className="flex flex-col gap-2">
                        {m.options.map((opt) => {
                          const STATUS_COLOR: Record<string, string> = {
                            placed:
                              'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
                            packed:
                              'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300',
                            out_for_delivery:
                              'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
                            delivered:
                              'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
                          };
                          // opt.description contains item names; derive status from label
                          const statusKey = opt.label.toLowerCase().includes('placed')
                            ? 'placed'
                            : opt.label.toLowerCase().includes('packed')
                              ? 'packed'
                              : opt.label.toLowerCase().includes('delivery')
                                ? 'out_for_delivery'
                                : opt.label.toLowerCase().includes('delivered')
                                  ? 'delivered'
                                  : 'placed';
                          const statusColor = STATUS_COLOR[statusKey] ?? '';
                          const statusMatch = opt.label.match(/—\s*(.+)$/);
                          const statusLabel = statusMatch ? statusMatch[1] : '';
                          return (
                            <div
                              key={opt.value}
                              className="border dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 p-3"
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-xs font-bold text-gray-700 dark:text-gray-300">
                                      {opt.label.split('—')[0] ?? opt.label}
                                    </span>
                                    {statusLabel !== '' && (
                                      <span
                                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${statusColor}`}
                                      >
                                        {statusLabel}
                                      </span>
                                    )}
                                  </div>
                                  {opt.description !== undefined && (
                                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 truncate">
                                      {opt.description}
                                    </p>
                                  )}
                                </div>
                                {/* Advance status button */}
                                {opt.actions !== undefined &&
                                  opt.actions.length > 0 &&
                                  !isConsumed && (
                                    <button
                                      onClick={() => {
                                        const firstAction = opt.actions?.[0];
                                        if (firstAction)
                                          handleOptionSelect(m.id, firstAction.value);
                                      }}
                                      className="shrink-0 px-2.5 py-1.5 bg-accent text-white rounded-lg text-[10px] font-bold hover:opacity-80 transition whitespace-nowrap"
                                    >
                                      {opt.actions[0]?.label}
                                    </button>
                                  )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                );
              }

              if (m.type === 'inventory' && m.options) {
                // Inventory card — first option may be the summary row (_summary)
                const summaryOpt = m.options.find(
                  (o) => o.value === '' || o.description?.includes('SKU') === true
                );
                const productOpts = m.options.filter(
                  (o) => o.value !== '' && o.description?.includes('SKU') !== true
                );
                const BADGE: Record<string, string> = {
                  '🟢': 'text-green-600',
                  '🟡': 'text-yellow-500',
                  '🔴': 'text-red-500',
                };
                return (
                  <div key={m.id} className="max-w-[95%] self-start w-full">
                    <div className="p-4 bg-gray-100 dark:bg-gray-900 rounded-2xl rounded-tl-none border dark:border-gray-800">
                      {m.content && (
                        <p className="text-sm font-bold text-gray-800 dark:text-gray-200 mb-3">
                          {m.content}
                        </p>
                      )}
                      <div className="flex flex-col gap-2">
                        {productOpts.map((opt) => {
                          const isConsumed = Boolean(selectedOptionByMsgId[m.id]);
                          // badge is first char of label
                          const badge = opt.label.slice(0, 2).trim();
                          const nameWithoutBadge = opt.label.slice(2).trim();
                          const badgeClass = BADGE[badge] ?? '';
                          return (
                            <div
                              key={opt.value}
                              className="border dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 p-3"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1.5">
                                    <span className={`text-base ${badgeClass}`}>{badge}</span>
                                    <span className="text-xs font-bold text-gray-700 dark:text-gray-300 truncate">
                                      {nameWithoutBadge}
                                    </span>
                                  </div>
                                  {opt.description !== undefined && (
                                    <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
                                      {opt.description}
                                    </p>
                                  )}
                                </div>
                                {opt.actions !== undefined &&
                                  opt.actions.length > 0 &&
                                  !isConsumed && (
                                    <div className="flex gap-1 shrink-0">
                                      {opt.actions.map((action) => (
                                        <button
                                          key={action.value}
                                          onClick={() => handleOptionSelect(m.id, action.value)}
                                          className="px-2 py-1 bg-accent-bg text-accent rounded-lg text-[10px] font-semibold hover:opacity-80 transition"
                                        >
                                          {action.label}
                                        </button>
                                      ))}
                                    </div>
                                  )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      {/* Summary footer */}
                      {summaryOpt && (
                        <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-3 text-right">
                          {summaryOpt.description}
                        </p>
                      )}
                    </div>
                  </div>
                );
              }

              if (m.type === 'options' && m.options) {
                return (
                  <div key={m.id} className="max-w-[90%] self-start w-full">
                    <div className="p-4 bg-gray-100 dark:bg-gray-900 rounded-2xl rounded-tl-none border dark:border-gray-800">
                      {m.content.length > 0 && (
                        <p className="text-sm font-medium text-gray-800 dark:text-gray-200 mb-3">
                          {m.content}
                        </p>
                      )}
                      <div className="flex flex-col gap-2">
                        {m.options.map((opt) => {
                          const selectedValue = selectedOptionByMsgId[m.id];
                          const isSelected = selectedValue === opt.value;
                          const isCardConsumed = Boolean(selectedValue);

                          if (isCardConsumed && !isSelected) {
                            return (
                              <div
                                key={opt.value}
                                className="w-full px-4 py-2 border rounded-xl text-left bg-gray-50 dark:bg-gray-900 border-gray-200 dark:border-gray-800 opacity-40"
                              >
                                <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                                  {opt.label}
                                </span>
                              </div>
                            );
                          }

                          return (
                            <div key={opt.value} className="w-full">
                              {isSelected ? (
                                <div className="w-full px-4 py-3 border rounded-xl text-left bg-accent-bg dark:bg-accent-bg border-accent-border dark:border-accent-border">
                                  <span className="text-[10px] text-accent dark:text-accent uppercase tracking-wider font-bold block mb-1">
                                    ✓ Selected
                                  </span>
                                  <span className="text-sm font-semibold text-heading dark:text-accent">
                                    {opt.label}
                                  </span>
                                </div>
                              ) : (
                                <>
                                  <button
                                    onClick={() => handleOptionSelect(m.id, opt.value)}
                                    disabled={isCardConsumed}
                                    className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-accent-bg dark:hover:bg-accent-bg border-gray-200 dark:border-gray-700"
                                  >
                                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                                      {opt.label}
                                    </span>
                                    {typeof opt.description === 'string' &&
                                      opt.description.length > 0 && (
                                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                                          {opt.description}
                                        </p>
                                      )}
                                  </button>
                                  {/* Quick action buttons */}
                                  {opt.actions && opt.actions.length > 0 && (
                                    <div className="flex gap-1.5 mt-1.5 px-1">
                                      {opt.actions.map((action) => {
                                        // Determine if this is a 'View Details' action - open in new tab
                                        const isViewDetails =
                                          action.label === 'View Details' &&
                                          action.value.startsWith('view_');
                                        if (isViewDetails) {
                                          const productId = action.value.replace('view_', '');
                                          return (
                                            <button
                                              key={action.value}
                                              onClick={() =>
                                                window.open(`/items/${productId}`, '_blank')
                                              }
                                              className="flex-1 px-2.5 py-1.5 bg-accent-bg dark:bg-accent-bg hover:bg-accent-bg dark:hover:bg-accent-bg text-accent dark:text-accent rounded-lg text-[11px] font-semibold transition"
                                            >
                                              {action.label}
                                            </button>
                                          );
                                        }
                                        return (
                                          <button
                                            key={action.value}
                                            onClick={() => handleOptionSelect(m.id, action.value)}
                                            className="flex-1 px-2.5 py-1.5 bg-accent-bg dark:bg-accent-bg hover:bg-accent-bg dark:hover:bg-accent-bg text-accent dark:text-accent rounded-lg text-[11px] font-semibold transition"
                                          >
                                            {action.label}
                                          </button>
                                        );
                                      })}
                                    </div>
                                  )}
                                </>
                              )}
                            </div>
                          );
                        })}
                        {m.free_input_allowed === true && (
                          <div className="mt-2 pt-2 border-t dark:border-gray-700">
                            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                              Or type your own response:
                            </p>
                            <form
                              onSubmit={(e) => {
                                e.preventDefault();
                                const input = e.currentTarget.querySelector('input')?.value ?? '';
                                if (input.trim().length > 0 && !isSending) {
                                  // Send free text as a regular user message, NOT as an option
                                  setMessages((prev) => [
                                    ...prev,
                                    { id: nextId(), role: 'user', content: input.trim() },
                                  ]);
                                  void sendTextMessage(input.trim());
                                }
                                // Clear the input after sending
                                const inputEl = e.currentTarget.querySelector('input');
                                if (inputEl) inputEl.value = '';
                              }}
                              className="flex gap-2"
                            >
                              <input
                                type="text"
                                placeholder="Type here..."
                                maxLength={500}
                                disabled={false}
                                className="flex-1 px-3 py-2 border dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-accent"
                              />
                              <button
                                type="submit"
                                disabled={isSending}
                                className="px-3 py-2 bg-accent text-white rounded-lg text-xs font-bold hover:bg-accent-hover transition disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                Send
                              </button>
                            </form>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              }

              const isUser = m.role === 'user';

              return (
                <div
                  key={m.id}
                  className={`max-w-[80%] p-3 rounded-2xl text-sm ${
                    isUser
                      ? 'bg-accent text-white self-end rounded-tr-none'
                      : m.content === ''
                        ? 'bg-gray-100 dark:bg-gray-900 self-start rounded-tl-none border dark:border-gray-800'
                        : 'bg-gray-100 dark:bg-gray-900 text-gray-800 dark:text-gray-200 self-start rounded-tl-none border dark:border-gray-800'
                  }`}
                >
                  {m.content.length > 0 ? (
                    m.content
                  ) : (
                    <div className="flex gap-1.5 items-center justify-center py-2">
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                      <span
                        className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                        style={{ animationDelay: '0.2s' }}
                      />
                      <span
                        className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                        style={{ animationDelay: '0.4s' }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
            {/* Show dots only when sending AND no status message is active */}
            {isSending &&
              !messages.some((m) => m.type === 'status') &&
              (messages.length === 0 ||
                messages[messages.length - 1]?.role !== 'assistant' ||
                messages[messages.length - 1]?.type !== 'text') && (
                <div className="max-w-[80%] p-3 rounded-2xl text-sm bg-gray-100 dark:bg-gray-900 text-gray-800 dark:text-gray-200 self-start rounded-tl-none border dark:border-gray-800">
                  <div className="flex gap-1.5 items-center justify-center py-2">
                    <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                    <span
                      className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                      style={{ animationDelay: '0.2s' }}
                    />
                    <span
                      className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                      style={{ animationDelay: '0.4s' }}
                    />
                  </div>
                </div>
              )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <form
            onSubmit={handleTextSubmit}
            className="p-4 border-t dark:border-gray-900 flex gap-3 bg-white dark:bg-gray-950 shrink-0"
          >
            <input
              ref={inputRef}
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder={chatError ? 'Connection error...' : 'Type your message...'}
              maxLength={500}
              disabled={isSending || chatError}
              className="flex-1 px-4 py-2.5 border dark:border-gray-800 bg-transparent rounded-xl focus:outline-none focus:ring-2 focus:ring-accent/50 text-sm disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isSending || chatError || textInput.trim().length === 0}
              className="p-2.5 bg-accent text-white rounded-xl hover:bg-accent-hover disabled:opacity-50 dark:disabled:bg-gray-800 transition flex items-center justify-center"
            >
              <Send size={18} />
            </button>
          </form>
        </>
      )}

      {/* Voice Chat Panel */}
      {mode === 'voice' && (
        <div className="flex-1 p-6 flex flex-col justify-between items-center bg-app">
          <div className="text-center space-y-6 w-full max-w-sm">
            {voiceState.error !== null && (
              <div className="p-4 border border-red-300 dark:border-red-950/40 bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 rounded-2xl text-xs font-semibold text-left flex items-start gap-2">
                <ShieldAlert size={16} className="shrink-0 mt-0.5" />
                <span>{voiceState.error}</span>
              </div>
            )}

            {/* Status */}
            <div>
              <div className="text-xs uppercase tracking-widest text-accent dark:text-accent font-bold mb-4">
                {voiceState.error !== null ? (
                  'Error'
                ) : (
                  <>
                    {voiceState.status === 'transcribing' && 'Listening...'}
                    {voiceState.status === 'thinking' && 'Thinking...'}
                    {voiceState.status === 'speaking' && 'Responding...'}
                    {voiceState.status === 'idle' && 'Tap the mic and speak'}
                    {voiceState.status === 'waiting_permission' && 'Verification Needed'}
                  </>
                )}
              </div>

              {/* Mic indicator */}
              <div className="flex justify-center py-4">
                <div className="relative">
                  {(voiceState.status === 'speaking' || voiceState.status === 'transcribing') && (
                    <>
                      <div className="absolute inset-0 rounded-full bg-accent-bg0/20 animate-ping" />
                      <div className="absolute inset-2 rounded-full bg-accent-bg animate-pulse" />
                    </>
                  )}
                  <div
                    className={`w-28 h-28 rounded-full flex items-center justify-center shadow-inner border-2 transition-all duration-500 ${
                      voiceState.status === 'transcribing'
                        ? 'bg-green-100 dark:bg-green-900/20 border-green-400 dark:border-green-600'
                        : voiceState.status === 'speaking'
                          ? 'bg-accent-bg dark:bg-accent-bg border-accent dark:border-accent'
                          : 'bg-accent-bg dark:bg-accent-bg border-accent-border dark:border-accent-border'
                    }`}
                  >
                    <Mic
                      size={44}
                      className={`transition-colors ${
                        voiceState.status === 'transcribing'
                          ? 'text-green-600 dark:text-green-400'
                          : 'text-accent dark:text-accent'
                      }`}
                    />
                  </div>
                </div>
              </div>

              {/* Transcript & Response Area */}
              <div className="w-full max-w-md min-h-[100px] max-h-[220px] overflow-y-auto px-4 py-3 border dark:border-gray-800 rounded-2xl bg-white/90 dark:bg-gray-950/90 backdrop-blur-sm text-left shadow-sm space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-bold tracking-wider text-accent">
                    Live Transcript
                  </span>
                  {voiceState.sttTiming !== null && (
                    <span className="text-[10px] text-gray-400 font-mono">
                      STT: {(voiceState.sttTiming * 1000).toFixed(0)}ms
                    </span>
                  )}
                </div>
                <p className="text-sm font-medium text-gray-800 dark:text-gray-200 leading-relaxed">
                  {voiceState.transcript.length > 0 ? (
                    voiceState.transcript
                  ) : (
                    <span className="text-gray-400 italic font-normal">
                      "Tap mic or speak into your microphone..."
                    </span>
                  )}
                </p>
              </div>
            </div>
          </div>

          {/* Options Request Card — branches by cardVariant for rich layouts */}
          {voiceState.optionsRequest &&
            voiceState.optionsRequest.options.length > 0 &&
            (() => {
              const req = voiceState.optionsRequest;
              const variant = req.cardVariant;

              // ── Fulfillment Queue Card ──────────────────────────────────
              if (variant === 'fulfillment_queue') {
                const STATUS_COLOR: Record<string, string> = {
                  placed: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
                  packed:
                    'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300',
                  out_for_delivery:
                    'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
                  delivered: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
                };
                return (
                  <div className="w-full max-w-sm p-4 glass-card text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <div className="flex items-center gap-2 text-accent font-bold text-xs uppercase tracking-wider">
                      <MessageSquare size={16} />
                      <span>Fulfillment Queue</span>
                    </div>
                    <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      {req.text}
                    </p>
                    <div className="flex flex-col gap-2 max-h-60 overflow-y-auto">
                      {req.options.map((opt) => {
                        const statusKey = opt.label.toLowerCase().includes('placed')
                          ? 'placed'
                          : opt.label.toLowerCase().includes('packed')
                            ? 'packed'
                            : opt.label.toLowerCase().includes('delivery')
                              ? 'out_for_delivery'
                              : opt.label.toLowerCase().includes('delivered')
                                ? 'delivered'
                                : 'placed';
                        const statusMatch = opt.label.match(/—\s*(.+)$/);
                        const statusLabel = statusMatch ? statusMatch[1] : '';
                        return (
                          <div
                            key={opt.value}
                            className="border dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 p-3"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex-1 min-w-0">
                                <span className="text-xs font-bold text-gray-700 dark:text-gray-300 block truncate">
                                  {opt.label.split('—')[0] ?? opt.label}
                                </span>
                                {statusLabel !== '' && (
                                  <span
                                    className={`text-[10px] font-bold px-2 py-0.5 rounded-full mt-1 inline-block ${STATUS_COLOR[statusKey] ?? ''}`}
                                  >
                                    {statusLabel}
                                  </span>
                                )}
                                {opt.description !== undefined && (
                                  <p className="text-xs text-gray-500 mt-0.5 truncate">
                                    {opt.description}
                                  </p>
                                )}
                              </div>
                              {opt.actions !== undefined && opt.actions.length > 0 && (
                                <button
                                  onClick={() => {
                                    const firstAction = opt.actions?.[0];
                                    if (firstAction) sendVoiceMessage(firstAction.value);
                                  }}
                                  className="shrink-0 px-2.5 py-1.5 bg-accent text-white rounded-lg text-[10px] font-bold hover:opacity-80 transition whitespace-nowrap"
                                >
                                  {opt.actions[0]?.label}
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              }

              // ── Inventory Card ──────────────────────────────────────────
              if (variant === 'inventory') {
                const productOpts = req.options.filter((o) => o.value !== '');
                const BADGE: Record<string, string> = {
                  '🟢': 'text-green-600',
                  '🟡': 'text-yellow-500',
                  '🔴': 'text-red-500',
                };
                return (
                  <div className="w-full max-w-sm p-4 glass-card text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
                    <div className="flex items-center gap-2 text-accent font-bold text-xs uppercase tracking-wider">
                      <MessageSquare size={16} />
                      <span>Inventory</span>
                    </div>
                    <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      {req.text}
                    </p>
                    <div className="flex flex-col gap-2 max-h-60 overflow-y-auto">
                      {productOpts.map((opt) => {
                        const badge = opt.label.slice(0, 2).trim();
                        const name = opt.label.slice(2).trim();
                        return (
                          <div
                            key={opt.value}
                            className="border dark:border-gray-700 rounded-xl bg-white dark:bg-gray-800 p-3"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className={`text-base ${BADGE[badge] ?? ''}`}>{badge}</span>
                                  <span className="text-xs font-bold text-gray-700 dark:text-gray-300 truncate">
                                    {name}
                                  </span>
                                </div>
                                {opt.description !== undefined && (
                                  <p className="text-[11px] text-gray-500 mt-0.5">
                                    {opt.description}
                                  </p>
                                )}
                              </div>
                              {opt.actions !== undefined && opt.actions.length > 0 && (
                                <div className="flex gap-1 shrink-0">
                                  {opt.actions.map((action) => (
                                    <button
                                      key={action.value}
                                      onClick={() => sendVoiceMessage(action.value)}
                                      className="px-2 py-1 bg-accent-bg text-accent rounded-lg text-[10px] font-semibold hover:opacity-80 transition"
                                    >
                                      {action.label}
                                    </button>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {req.freeInputAllowed && (
                      <div className="pt-2 border-t dark:border-gray-700">
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            const inputEl =
                              e.currentTarget.querySelector<HTMLInputElement>('input');
                            const inp = inputEl?.value ?? '';
                            if (inp.trim()) sendVoiceMessage(inp.trim());
                            if (inputEl) inputEl.value = '';
                          }}
                          className="flex gap-2"
                        >
                          <input
                            type="text"
                            placeholder="Filter inventory..."
                            maxLength={200}
                            className="flex-1 px-3 py-2 border dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-accent"
                          />
                          <button
                            type="submit"
                            className="px-3 py-2 bg-accent text-white rounded-lg text-xs font-bold hover:opacity-80 transition"
                          >
                            Go
                          </button>
                        </form>
                      </div>
                    )}
                  </div>
                );
              }

              // ── Generic Options Card (default) ──────────────────────────
              return (
                <div className="w-full max-w-sm p-4 glass-card text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
                  <div className="flex items-center gap-2 text-accent font-bold text-xs uppercase tracking-wider">
                    <MessageSquare size={16} />
                    <span>Choose an option</span>
                  </div>
                  <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 leading-relaxed">
                    {req.text}
                  </p>
                  <div className="flex flex-col gap-2">
                    {req.options.map((opt) => (
                      <button
                        key={opt.value}
                        onClick={() => sendVoiceMessage(opt.value)}
                        className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-accent-bg dark:hover:bg-accent-bg border-gray-200 dark:border-gray-700"
                      >
                        <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                          {opt.label}
                        </span>
                        {opt.description != null && opt.description !== '' && (
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                            {opt.description}
                          </p>
                        )}
                        {opt.actions && opt.actions.length > 0 && (
                          <div className="flex gap-1.5 mt-1.5 flex-wrap">
                            {opt.actions.map((action) => (
                              <button
                                key={action.value}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  sendVoiceMessage(action.value);
                                }}
                                className="px-2.5 py-1 bg-accent-bg text-accent rounded-lg text-[10px] font-semibold hover:opacity-80 transition"
                              >
                                {action.label}
                              </button>
                            ))}
                          </div>
                        )}
                      </button>
                    ))}
                  </div>
                  {req.freeInputAllowed && (
                    <div className="pt-2 border-t dark:border-gray-700">
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                        Or type your response:
                      </p>
                      <form
                        onSubmit={(e) => {
                          e.preventDefault();
                          const input = e.currentTarget.querySelector('input')?.value ?? '';
                          if (input.trim().length > 0) sendVoiceMessage(input.trim());
                          const inputEl = e.currentTarget.querySelector('input');
                          if (inputEl) inputEl.value = '';
                        }}
                        className="flex gap-2"
                      >
                        <input
                          type="text"
                          placeholder="Type here..."
                          maxLength={500}
                          className="flex-1 px-3 py-2 border dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-accent"
                        />
                        <button
                          type="submit"
                          className="px-3 py-2 bg-accent text-white rounded-lg text-xs font-bold hover:bg-accent-hover transition"
                        >
                          Send
                        </button>
                      </form>
                    </div>
                  )}
                </div>
              );
            })()}

          {/* Role Switch Request Card */}
          {voiceState.roleSwitchRequest && (
            <div className="w-full max-w-sm p-4 glass-card text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <div className="flex items-center gap-2 text-accent font-bold text-xs uppercase tracking-wider">
                <ShieldAlert size={16} />
                <span>Role Switch Required</span>
              </div>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 leading-relaxed">
                {voiceState.roleSwitchRequest.text}
              </p>
              <div className="flex flex-col gap-2">
                {voiceState.roleSwitchRequest.options.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => sendVoiceMessage(opt.value)}
                    className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-accent-bg dark:hover:bg-accent-bg border-gray-200 dark:border-gray-700"
                  >
                    <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                      {opt.label}
                    </span>
                    {opt.description != null && opt.description !== '' && (
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        {opt.description}
                      </p>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Permission Request Card */}
          {voiceState.status === 'waiting_permission' && voiceState.permissionRequest && (
            <div className="w-full max-w-sm p-4 glass-card text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <div className="flex items-center gap-2 text-amber-500 font-bold text-xs uppercase tracking-wider">
                <ShieldAlert size={16} />
                <span>Permission Requested</span>
              </div>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 leading-relaxed">
                {voiceState.permissionRequest.summary}
              </p>
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => sendPermissionResponse(true)}
                  className="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-xl text-xs font-bold transition"
                >
                  Yes, approve
                </button>
                <button
                  onClick={() => sendPermissionResponse(false)}
                  className="px-4 py-2 bg-gray-200 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-xl text-xs font-bold transition"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Control Actions */}
          <div className="flex gap-4">
            <button
              onClick={handleBackToSelect}
              className="py-2.5 px-8 bg-red-500 hover:bg-red-600 text-white rounded-full font-bold text-sm transition"
            >
              Disconnect
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default Agent;