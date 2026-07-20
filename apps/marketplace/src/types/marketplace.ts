/**
 * Marketplace TypeScript types
 */

export interface Task {
  id: string;
  author_principal: string;
  description: string;
  status: 'open' | 'accepted' | 'completed';
  created_at: string;
  worker_principal: string | null;
  negotiations: NegotiationMessage[];
  outcome: string | null;
}

export interface NegotiationMessage {
  from: string;
  message: string;
  timestamp: string;
}

export interface TaskResponse {
  task: Task;
}

export interface TaskListResponse {
  tasks: Task[];
  total: number;
  skip: number;
  limit: number;
}

export interface NegotiationResponse {
  message: NegotiationMessage;
  task: Task;
}

export interface NegotiationsResponse {
  task_id: string;
  negotiations: NegotiationMessage[];
}
