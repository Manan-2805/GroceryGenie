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
import { authService } from '../services/api';
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
    'text' | 'permission' | 'options' | 'navigation' | 'action_card' | 'status' | 'role_switch';
  options?: OptionItem[];
  free_input_allowed?: boolean;
  navigate_to?: string;
  navigate_label?: string;
  action_data?: Record<string, unknown>;
  needed_role?: string;
  original_tool?: string;
};

type StreamEvent =
  | { type: 'delta'; text: string }
  | { type: 'status'; status: string }
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
    }
  | { type: 'response'; text: string; options?: unknown[]; free_input_allowed?: boolean };

// eslint-disable-next-line @typescript-eslint/no-unused-vars
let _messageIdCounter = 0;
const nextId = () => {
  _messageIdCounter += 1;
  return `msg-${_messageIdCounter}-${Date.now()}`;
};

export const Agent: React.FC = () => {
  const navigate = useNavigate();
  const { sessionId, setSessionId, voiceOk } = useUIStore();
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

  useEffect(() => {
    // Fetch user name for greeting
    authService
      .getMe()
      .then((data) => setUserName(data.name))
      .catch((e) => {
        console.error('Failed to fetch user info:', e);
      });
  }, []);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, voiceState.transcript, voiceState.status]);

  const handleStartTextChat = () => {
    setMode('text');
    setChatError(false);
    setMessages([
      {
        id: nextId(),
        role: 'assistant',
        content: `Hi ${userName !== '' ? userName : 'there'}! I'm your GroceryGenie assistant. I can help you find products, manage your cart, check orders, manage addresses, and more. How can I help?`,
      },
    ]);
    setSessionId(window.crypto.randomUUID());
    window.setTimeout(() => {
      inputRef.current?.focus();
    }, 100);
  };

  const handleStartVoiceChat = async () => {
    setMode('voice');
    const newSessionId = window.crypto.randomUUID();
    setSessionId(newSessionId);
    await startSession(newSessionId);
  };

  const handleBackToSelect = () => {
    if (mode === 'voice') {
      endSession();
    }
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

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantResponse = '';

      let hasMoreChunks = true;
      while (hasMoreChunks) {
        const { value, done } = await reader.read();
        if (done) {
          hasMoreChunks = false;
          continue;
        }

        const rawText = decoder.decode(value);
        const lines = rawText.split('\n');

        for (const line of lines) {
          if (line.startsWith('data:')) {
            const dataStr = line.replace('data:', '').trim();
            try {
              const data = JSON.parse(dataStr) as Partial<StreamEvent> & Record<string, unknown>;

              if (data.type === 'status' && typeof data.status === 'string') {
                // Status update from orchestrator (show briefly)
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
                // Auto-remove status after 3 seconds
                window.setTimeout(() => {
                  setMessages((prev) => prev.filter((m) => m.type !== 'status'));
                }, 3000);
              } else if (data.type === 'delta' && typeof data.text === 'string') {
                assistantResponse += data.text;
                // Update the last assistant message in real-time
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
                const neededRole =
                  typeof data.needed_role === 'string' ? data.needed_role : 'seller';
                const originalTool =
                  typeof data.original_tool === 'string' ? data.original_tool : '';
                const roleOptions: OptionItem[] = Array.isArray(data.options)
                  ? data.options.filter(
                      (
                        opt: unknown
                      ): opt is { label: string; value: string; description?: string } =>
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
                setMessages((prev) => [
                  ...prev,
                  {
                    id: nextId(),
                    role: 'assistant',
                    content: typeof data.text === 'string' ? data.text : '',
                    type: 'options',
                    options: Array.isArray(data.options)
                      ? data.options.filter(
                          (
                            option
                          ): option is {
                            label: string;
                            value: string;
                            description?: string;
                          } =>
                            typeof option === 'object' &&
                            option !== null &&
                            'label' in option &&
                            'value' in option
                        )
                      : [],
                    free_input_allowed: data.free_input_allowed !== false,
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
              // Parsing error - skip
            }
          }
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
    <div className="h-[calc(100vh-8rem)] flex flex-col bg-white dark:bg-gray-950 rounded-2xl border border-gray-200 dark:border-gray-900 overflow-hidden shadow-xl">
      {/* Header */}
      <div className="p-4 bg-gradient-to-r from-purple-600 to-indigo-600 text-white flex items-center justify-between shrink-0">
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
            <p className="text-[10px] text-purple-100">
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
                className="w-full p-6 flex items-center gap-4 border-2 border-purple-200 hover:border-purple-500 rounded-2xl hover:bg-purple-50 dark:hover:bg-purple-950/20 transition-all group"
              >
                <div className="w-14 h-14 rounded-xl bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center group-hover:scale-105 transition">
                  <MessageSquare size={28} className="text-purple-600" />
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
                    ? 'border-purple-200 hover:border-purple-500 hover:bg-purple-50 dark:hover:bg-purple-950/20'
                    : 'border-gray-200 dark:border-gray-800 opacity-40 cursor-not-allowed'
                }`}
              >
                <div className="w-14 h-14 rounded-xl bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center group-hover:scale-105 transition">
                  <Mic size={28} className="text-purple-600" />
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
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 dark:bg-gray-900 hover:bg-purple-50 dark:hover:bg-purple-950/20 rounded-full text-xs font-medium text-gray-600 dark:text-gray-400 transition border dark:border-gray-800"
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
                    <div className="p-4 border rounded-2xl border-purple-300 dark:border-purple-500 bg-purple-50 dark:bg-purple-950/20">
                      <div className="flex items-center gap-2 text-purple-600 dark:text-purple-400 font-semibold mb-2 text-xs uppercase tracking-wider">
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
                                  <div className="w-full px-4 py-3 border rounded-xl text-left bg-purple-50 dark:bg-purple-950/30 border-purple-300 dark:border-purple-800">
                                    <span className="text-[10px] text-purple-600 dark:text-purple-400 uppercase tracking-wider font-bold block mb-1">
                                      ✓ Selected
                                    </span>
                                    <span className="text-sm font-semibold text-purple-900 dark:text-purple-200">
                                      {opt.label}
                                    </span>
                                  </div>
                                ) : (
                                  <button
                                    onClick={() => handleOptionSelect(m.id, opt.value)}
                                    disabled={isCardConsumed}
                                    className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-purple-50 dark:hover:bg-purple-950/20 border-gray-200 dark:border-gray-700"
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
                                <div className="w-full px-4 py-3 border rounded-xl text-left bg-purple-50 dark:bg-purple-950/30 border-purple-300 dark:border-purple-800">
                                  <span className="text-[10px] text-purple-600 dark:text-purple-400 uppercase tracking-wider font-bold block mb-1">
                                    ✓ Selected
                                  </span>
                                  <span className="text-sm font-semibold text-purple-900 dark:text-purple-200">
                                    {opt.label}
                                  </span>
                                </div>
                              ) : (
                                <>
                                  <button
                                    onClick={() => handleOptionSelect(m.id, opt.value)}
                                    disabled={isCardConsumed}
                                    className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-purple-50 dark:hover:bg-purple-950/20 border-gray-200 dark:border-gray-700"
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
                                              className="flex-1 px-2.5 py-1.5 bg-purple-100 dark:bg-purple-900/30 hover:bg-purple-200 dark:hover:bg-purple-800/40 text-purple-700 dark:text-purple-300 rounded-lg text-[11px] font-semibold transition"
                                            >
                                              {action.label}
                                            </button>
                                          );
                                        }
                                        return (
                                          <button
                                            key={action.value}
                                            onClick={() => handleOptionSelect(m.id, action.value)}
                                            className="flex-1 px-2.5 py-1.5 bg-purple-100 dark:bg-purple-900/30 hover:bg-purple-200 dark:hover:bg-purple-800/40 text-purple-700 dark:text-purple-300 rounded-lg text-[11px] font-semibold transition"
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
                                className="flex-1 px-3 py-2 border dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                              />
                              <button
                                type="submit"
                                disabled={isSending}
                                className="px-3 py-2 bg-purple-600 text-white rounded-lg text-xs font-bold hover:bg-purple-700 transition disabled:bg-purple-400 disabled:cursor-not-allowed"
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
                      ? 'bg-purple-600 text-white self-end rounded-tr-none'
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
              className="flex-1 px-4 py-2.5 border dark:border-gray-800 bg-transparent rounded-xl focus:outline-none focus:ring-2 focus:ring-purple-600/50 text-sm disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isSending || chatError || textInput.trim().length === 0}
              className="p-2.5 bg-purple-600 text-white rounded-xl hover:bg-purple-700 disabled:bg-purple-400 dark:disabled:bg-gray-800 transition flex items-center justify-center"
            >
              <Send size={18} />
            </button>
          </form>
        </>
      )}

      {/* Voice Chat Panel */}
      {mode === 'voice' && (
        <div className="flex-1 p-6 flex flex-col justify-between items-center bg-gradient-to-b from-gray-50 to-white dark:from-gray-900 dark:to-gray-950">
          <div className="text-center space-y-6 w-full max-w-sm">
            {voiceState.error !== null && (
              <div className="p-4 border border-red-300 dark:border-red-950/40 bg-red-50 dark:bg-red-950/20 text-red-600 dark:text-red-400 rounded-2xl text-xs font-semibold text-left flex items-start gap-2">
                <ShieldAlert size={16} className="shrink-0 mt-0.5" />
                <span>{voiceState.error}</span>
              </div>
            )}

            {/* Status */}
            <div>
              <div className="text-xs uppercase tracking-widest text-purple-600 dark:text-purple-400 font-bold mb-4">
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
                      <div className="absolute inset-0 rounded-full bg-purple-500/20 animate-ping" />
                      <div className="absolute inset-2 rounded-full bg-purple-400/10 animate-pulse" />
                    </>
                  )}
                  <div
                    className={`w-28 h-28 rounded-full flex items-center justify-center shadow-inner border-2 transition-all duration-500 ${
                      voiceState.status === 'transcribing'
                        ? 'bg-green-100 dark:bg-green-900/20 border-green-400 dark:border-green-600'
                        : voiceState.status === 'speaking'
                          ? 'bg-purple-100 dark:bg-purple-900/20 border-purple-400 dark:border-purple-600'
                          : 'bg-purple-100 dark:bg-purple-900/20 border-purple-200 dark:border-purple-900/50'
                    }`}
                  >
                    <Mic
                      size={44}
                      className={`transition-colors ${
                        voiceState.status === 'transcribing'
                          ? 'text-green-600 dark:text-green-400'
                          : 'text-purple-600 dark:text-purple-400'
                      }`}
                    />
                  </div>
                </div>
              </div>

              {/* Transcript & Response Area */}
              <div className="w-full max-w-md min-h-[100px] max-h-[220px] overflow-y-auto px-4 py-3 border dark:border-gray-800 rounded-2xl bg-white/90 dark:bg-gray-950/90 backdrop-blur-sm text-left shadow-sm space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase font-bold tracking-wider text-purple-500">
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

          {/* Options Request Card */}
          {voiceState.optionsRequest && voiceState.optionsRequest.options.length > 0 && (
            <div className="w-full max-w-sm p-4 border dark:border-gray-800 rounded-2xl bg-white dark:bg-gray-950 shadow-lg text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <div className="flex items-center gap-2 text-purple-500 font-bold text-xs uppercase tracking-wider">
                <MessageSquare size={16} />
                <span>Choose an option</span>
              </div>
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 leading-relaxed">
                {voiceState.optionsRequest.text}
              </p>
              <div className="flex flex-col gap-2">
                {voiceState.optionsRequest.options.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => sendVoiceMessage(opt.value)}
                    className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-purple-50 dark:hover:bg-purple-950/20 border-gray-200 dark:border-gray-700"
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
              {voiceState.optionsRequest.freeInputAllowed && (
                <div className="pt-2 border-t dark:border-gray-700">
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                    Or type your response:
                  </p>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      const input = e.currentTarget.querySelector('input')?.value ?? '';
                      if (input.trim().length > 0) {
                        sendVoiceMessage(input.trim());
                      }
                      const inputEl = e.currentTarget.querySelector('input');
                      if (inputEl) inputEl.value = '';
                    }}
                    className="flex gap-2"
                  >
                    <input
                      type="text"
                      placeholder="Type here..."
                      maxLength={500}
                      className="flex-1 px-3 py-2 border dark:border-gray-700 bg-white dark:bg-gray-800 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-purple-600"
                    />
                    <button
                      type="submit"
                      className="px-3 py-2 bg-purple-600 text-white rounded-lg text-xs font-bold hover:bg-purple-700 transition"
                    >
                      Send
                    </button>
                  </form>
                </div>
              )}
            </div>
          )}

          {/* Role Switch Request Card */}
          {voiceState.roleSwitchRequest && (
            <div className="w-full max-w-sm p-4 border dark:border-gray-800 rounded-2xl bg-white dark:bg-gray-950 shadow-lg text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
              <div className="flex items-center gap-2 text-purple-500 font-bold text-xs uppercase tracking-wider">
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
                    className="w-full px-4 py-3 border rounded-xl text-left transition bg-white dark:bg-gray-800 hover:bg-purple-50 dark:hover:bg-purple-950/20 border-gray-200 dark:border-gray-700"
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
            <div className="w-full max-w-sm p-4 border dark:border-gray-800 rounded-2xl bg-white dark:bg-gray-950 shadow-lg text-left space-y-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
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
