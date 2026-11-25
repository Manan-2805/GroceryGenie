export type ResultRecord = {
  id: string;
  name: string;
  package?: string;
  price?: string;
  stock?: number;
  status?: string;
  quantity?: number;
};

export type AssistantEvent =
  | { type: 'response'; text: string; records?: ResultRecord[] }
  | { type: 'permission_request'; summary: string; confirmation_id: string };

export type ConversationMessage = {
  role: 'user' | 'assistant';
  content: string;
  confirmation_id?: string | null;
  records?: ResultRecord[];
};
