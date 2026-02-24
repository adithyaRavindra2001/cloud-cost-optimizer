'use client';

import { useState, useRef, useEffect } from 'react';
import { Sparkles, X, Send, MessageCircle } from 'lucide-react';
import { apiPost } from '../lib/api';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  tools_used?: string[];
}

interface ChatPanelProps {
  demo: boolean;
  credentialId?: string | null;
}

const SUGGESTED_QUESTIONS = [
  'What are my top cost drivers?',
  'Why is EC2 my biggest expense?',
  'Compare this month vs last month',
  'Are any of my RDS instances oversized?',
];

export default function ChatPanel({ demo, credentialId }: ChatPanelProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || loading) return;

    const userMsg: ChatMessage = { role: 'user', content: text.trim() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const body: Record<string, unknown> = {
        message: text.trim(),
        demo,
      };
      if (sessionId) body.session_id = sessionId;
      if (credentialId && !demo) body.credential_id = credentialId;

      const data = await apiPost('/api/chat', body);
      setSessionId(data.session_id);

      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: data.response,
        tools_used: data.tools_used?.length > 0 ? data.tools_used : undefined,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const uniqueTools = (tools: string[]) => [...new Set(tools)];

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 bg-purple-600 hover:bg-purple-700 text-white rounded-full px-5 py-3 shadow-lg transition-all hover:scale-105"
      >
        <Sparkles size={20} />
        <span className="font-medium">AI Assistant</span>
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 w-[400px] h-[600px] bg-white rounded-2xl shadow-2xl border border-gray-200 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-purple-600 text-white">
        <div className="flex items-center gap-2">
          <Sparkles size={18} />
          <span className="font-semibold">AI Cost Assistant</span>
        </div>
        <button onClick={() => setOpen(false)} className="hover:bg-purple-700 rounded p-1 transition">
          <X size={18} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <MessageCircle size={40} className="text-purple-300 mb-3" />
            <p className="text-gray-500 text-sm mb-4">
              Ask me anything about your AWS costs. I can investigate using real API calls.
            </p>
            <div className="space-y-2 w-full">
              {SUGGESTED_QUESTIONS.map((q, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(q)}
                  className="w-full text-left text-sm px-3 py-2 rounded-lg bg-purple-50 hover:bg-purple-100 text-purple-700 transition"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] ${msg.role === 'user' ? 'order-last' : ''}`}>
              <div
                className={`rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white rounded-br-md'
                    : 'bg-gray-100 text-gray-800 rounded-bl-md'
                }`}
              >
                {msg.content}
              </div>
              {msg.tools_used && msg.tools_used.length > 0 && (
                <p className="text-[10px] text-gray-400 mt-1 px-1">
                  Used: {uniqueTools(msg.tools_used).join(', ')}
                </p>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-2xl rounded-bl-md px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <span className="flex gap-1">
                  <span className="w-1.5 h-1.5 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </span>
                <span>Investigating...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-gray-200 p-3">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your AWS costs..."
            className="flex-1 text-sm px-3 py-2 rounded-lg border border-gray-300 focus:ring-2 focus:ring-purple-500 focus:border-transparent outline-none"
            disabled={loading}
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || loading}
            className="p-2 rounded-lg bg-purple-600 text-white hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition"
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
