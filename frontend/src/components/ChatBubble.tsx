import React, { useEffect, useRef, useState } from 'react';
import { MessageSquare, Mic, MicOff, Send, X, ShieldAlert, Navigation } from 'lucide-react';

import { useVoiceSession } from '../contexts/VoiceSessionContext';
import { api } from '../services/api';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

export const ChatBubble: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [mode, setMode] = useState<'select' | 'text' | 'voice'>('select');
  const [messages, setMessages] = useState<Message[]>([]);
  const [textInput, setTextInput] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);

  // Voice Session hook
  const { state: voiceState, startSession, endSession, sendPermissionResponse } = useVoiceSession();
  
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, voiceState.transcript, voiceState.status]);

  const handleStartTextChat = () => {
    setMode('text');
    setMessages([{ role: 'assistant', content: 'Hi! I am your AI assistant. How can I help you today?' }]);
    // Reset session ID
    setSessionId(uuidv4());
  };

  const handleStartVoiceChat = async () => {
    setMode('voice');
    const newSessionId = uuidv4();
    setSessionId(newSessionId);
    await startSession(newSessionId);
  };

  const handleClose = () => {
    if (mode === 'voice') {
      endSession();
    }
    setIsOpen(false);
    setMode('select');
  };

  const uuidv4 = () => {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      const r = (Math.random() * 16) | 0,
        v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  };

  // Text Mode SSE Stream Handler
  const sendTextMessage = async (
    msgText: string,
    approvedAction?: string,
    approvedPayload?: any
  ) => {
    if (!msgText.strip() && !approvedAction) return;

    if (!approvedAction) {
      setMessages((prev) => [...prev, { role: 'user', content: msgText }]);
      setTextInput('');
    }
    
    setIsSending(true);

    try {
      // We add a loading placeholder assistant message
      setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

      const response = await fetch('http://localhost:8000/api/v1/chat/text', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: msgText,
          session_id: sessionId,
          approved_action: approvedAction,
          approved_payload: approvedPayload,
        }),
      });

      if (!response.body) throw new Error('No response stream body');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantResponse = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const rawText = decoder.decode(value);
        const lines = rawText.split('\n');

        for (const line of lines) {
          if (line.startsWith('event:')) {
            // Check event type
            const eventType = line.replace('event:', '').strip();
            if (eventType === 'permission_request') {
              // We will parse data in next line
            }
          }
          if (line.startsWith('data:')) {
            const dataStr = line.replace('data:', '').strip();
            try {
              const data = JSON.parse(dataStr);
              if (data.type === 'delta') {
                assistantResponse += data.text;
                setMessages((prev) => {
                  const updated = [...prev];
                  updated[updated.length - 1] = { role: 'assistant', content: assistantResponse };
                  return updated;
                });
              } else if (data.type === 'permission_request') {
                // Intercept permission request inside text chat
                setMessages((prev) => {
                  const updated = [...prev];
                  // Remove loading placeholder
                  updated.pop();
                  return updated;
                });
                
                // Expose a local permission UI in text chat
                setMessages((prev) => [
                  ...prev,
                  {
                    role: 'assistant',
                    content: `[PERMISSION_REQUEST] ${data.summary}|${data.action}|${JSON.stringify(data.payload)}`,
                  },
                ]);
              } else if (data.type === 'navigate_to') {
                // Trigger global navigation event
                window.dispatchEvent(
                  new CustomEvent('agent-navigate', {
                    detail: { path: data.path, label: data.label },
                  })
                );
              }
            } catch (e) {
              // Parsing error
            }
          }
        }
      }
    } catch (e) {
      console.error(e);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I encountered an error processing that.' },
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const handleTextSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendTextMessage(textInput);
  };

  const renderPermissionBox = (summary: string, action: string, payloadStr: string) => {
    const payload = JSON.parse(payloadStr);
    return (
      <div className="p-3 my-2 border rounded-xl glassmorphism border-amber-300 dark:border-amber-500 bg-amber-50 dark:bg-amber-950/20 text-left">
        <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 font-semibold mb-2">
          <ShieldAlert size={18} />
          <span>Permission Required</span>
        </div>
        <p className="text-sm font-medium mb-3">{summary}</p>
        <div className="flex gap-2">
          <button
            onClick={() => sendTextMessage(`Approved: ${action}`, action, payload)}
            className="px-3 py-1 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-xs font-semibold"
          >
            Yes, proceed
          </button>
          <button
            onClick={() =>
              setMessages((prev) => [
                ...prev.filter((m) => !m.content.includes(summary)),
                { role: 'assistant', content: 'Action cancelled.' },
              ])
            }
            className="px-3 py-1 bg-gray-200 dark:bg-gray-800 hover:bg-gray-300 text-gray-800 dark:text-gray-200 rounded-lg text-xs font-semibold"
          >
            No, cancel
          </button>
        </div>
      </div>
    );
  };

  // Helper string extension for quick cleaning
  String.prototype.strip = function () {
    return this.trim();
  };

  return (
    <>
      {/* Floating Chat Bubble */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed bottom-6 right-6 p-4 bg-gradient-to-tr from-purple-600 to-indigo-600 hover:scale-105 active:scale-95 shadow-xl hover:shadow-purple-500/20 text-white rounded-full z-50 transition-all duration-300 animate-bounce"
        >
          <MessageSquare size={24} />
        </button>
      )}

      {/* Fullscreen Overlay Chat Panel */}
      {isOpen && (
        <div className="fixed inset-0 md:left-auto md:top-auto md:bottom-6 md:right-6 md:w-[420px] md:h-[600px] w-full h-full bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-900 rounded-none md:rounded-2xl shadow-2xl flex flex-col z-50 overflow-hidden transition-all duration-300">
          {/* Header */}
          <div className="p-4 bg-gradient-to-r from-purple-600 to-indigo-600 text-white flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center font-bold">
                GG
              </div>
              <div>
                <h3 className="font-semibold text-sm">GroceryGenie</h3>
                <p className="text-[10px] text-purple-100">
                  {mode === 'voice' ? 'Voice Mode Active' : 'Online'}
                </p>
              </div>
            </div>
            <button onClick={handleClose} className="hover:bg-white/20 p-1 rounded-full">
              <X size={20} />
            </button>
          </div>

          {/* Mode Selection */}
          {mode === 'select' && (
            <div className="flex-1 p-6 flex flex-col justify-center items-center gap-6">
              <h2 className="text-xl font-bold text-center text-gray-800 dark:text-gray-200">
                Choose Chat Mode
              </h2>
              <div className="flex gap-4 w-full">
                <button
                  onClick={handleStartTextChat}
                  className="flex-1 py-4 px-3 flex flex-col items-center justify-center gap-2 border border-purple-200 hover:border-purple-600 rounded-xl hover:bg-purple-50 dark:hover:bg-purple-950/20 transition-all"
                >
                  <MessageSquare size={32} className="text-purple-600" />
                  <span className="font-semibold text-sm">Text Chat</span>
                </button>
                <button
                  onClick={handleStartVoiceChat}
                  className="flex-1 py-4 px-3 flex flex-col items-center justify-center gap-2 border border-purple-200 hover:border-purple-600 rounded-xl hover:bg-purple-50 dark:hover:bg-purple-950/20 transition-all"
                >
                  <Mic size={32} className="text-purple-600 animate-pulse" />
                  <span className="font-semibold text-sm">Voice Chat</span>
                </button>
              </div>
            </div>
          )}

          {/* Text Chat Panel */}
          {mode === 'text' && (
            <>
              {/* Message List */}
              <div className="flex-1 p-4 overflow-y-auto space-y-3 flex flex-col">
                {messages.map((m, idx) => {
                  const isUser = m.role === 'user';
                  const isPermissionRequest = m.content.startsWith('[PERMISSION_REQUEST]');
                  
                  if (isPermissionRequest) {
                    const parts = m.content.replace('[PERMISSION_REQUEST] ', '').split('|');
                    return (
                      <div key={idx}>
                        {renderPermissionBox(parts[0], parts[1], parts[2])}
                      </div>
                    );
                  }

                  return (
                    <div
                      key={idx}
                      className={`max-w-[80%] p-3 rounded-2xl text-sm ${
                        isUser
                          ? 'bg-purple-600 text-white self-end rounded-tr-none'
                          : 'bg-gray-100 dark:bg-gray-900 text-gray-800 dark:text-gray-200 self-start rounded-tl-none'
                      }`}
                    >
                      {m.content || (
                        <div className="flex gap-1 items-center justify-center py-1">
                          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></span>
                          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]"></span>
                          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:0.4s]"></span>
                        </div>
                      )}
                    </div>
                  );
                })}
                <div ref={messagesEndRef} />
              </div>

              {/* Message Input */}
              <form onSubmit={handleTextSubmit} className="p-3 border-t dark:border-gray-900 flex gap-2">
                <input
                  type="text"
                  value={textInput}
                  onChange={(e) => setTextInput(e.target.value)}
                  placeholder="Type your message..."
                  className="flex-1 px-4 py-2 border dark:border-gray-800 bg-transparent rounded-full focus:outline-none focus:ring-1 focus:ring-purple-600 text-sm"
                />
                <button
                  type="submit"
                  disabled={isSending}
                  className="p-2 bg-purple-600 text-white rounded-full hover:bg-purple-700 disabled:bg-purple-400 transition"
                >
                  <Send size={18} />
                </button>
              </form>
            </>
          )}

          {/* Voice Chat Panel */}
          {mode === 'voice' && (
            <div className="flex-1 p-6 flex flex-col justify-between items-center bg-gray-50 dark:bg-gray-900/10">
              <div className="text-center space-y-4">
                <h4 className="text-xs uppercase tracking-widest text-purple-600 dark:text-purple-400 font-bold">
                  {voiceState.status === 'transcribing' && 'Listening...'}
                  {voiceState.status === 'thinking' && 'Thinking...'}
                  {voiceState.status === 'speaking' && 'Responding...'}
                  {voiceState.status === 'idle' && 'Tap mic to talk'}
                  {voiceState.status === 'waiting_permission' && 'Verification Needed'}
                </h4>

                {/* Animated wave bubble */}
                <div className="flex justify-center my-8">
                  <div
                    className={`p-8 rounded-full border-4 ${
                      voiceState.status === 'speaking'
                        ? 'border-green-500 bg-green-500/10 animate-pulse'
                        : voiceState.status === 'thinking'
                          ? 'border-indigo-500 bg-indigo-500/10 animate-spin [animation-duration:3s]'
                          : voiceState.status === 'transcribing'
                            ? 'border-purple-600 bg-purple-600/10 animate-ping'
                            : 'border-purple-300 dark:border-purple-900'
                    }`}
                  >
                    <Mic size={48} className="text-purple-600 dark:text-purple-400" />
                  </div>
                </div>

                {/* Real-time transcript display */}
                <div className="min-h-[60px] max-w-[280px] mx-auto text-sm italic text-gray-700 dark:text-gray-300 font-medium">
                  "{voiceState.transcript || 'Speak now...'}"
                </div>
              </div>

              {/* Permission Alert Box for Voice Mode */}
              {voiceState.permissionRequest && (
                <div className="w-full p-4 border border-amber-300 dark:border-amber-500 bg-amber-50 dark:bg-amber-950/20 rounded-xl mb-4 text-left">
                  <div className="flex items-center gap-2 text-amber-600 dark:text-amber-400 font-bold mb-2">
                    <ShieldAlert size={16} />
                    <span className="text-xs">Cart Approval Required</span>
                  </div>
                  <p className="text-xs font-semibold mb-3">{voiceState.permissionRequest.summary}</p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => sendPermissionResponse(true)}
                      className="px-3 py-1 bg-amber-500 text-white rounded-lg text-xs font-bold"
                    >
                      Yes, approve
                    </button>
                    <button
                      onClick={() => sendPermissionResponse(false)}
                      className="px-3 py-1 bg-gray-200 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg text-xs font-bold"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {/* Control Actions */}
              <div className="flex gap-4">
                <button
                  onClick={endSession}
                  className="py-2 px-6 bg-red-500 hover:bg-red-600 text-white rounded-full font-bold text-sm transition"
                >
                  Disconnect
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
};

// TS declaration for custom strip helper on String
declare global {
  interface String {
    strip(): string;
  }
}
