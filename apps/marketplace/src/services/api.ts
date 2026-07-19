/**
 * Marketplace API client
 *
 * Handles all communication with the marketplace backend server
 */

import {
  Task,
  TaskResponse,
  TaskListResponse,
  NegotiationResponse,
  NegotiationsResponse,
} from '../types/marketplace';

const API_BASE_URL = process.env.REACT_APP_MARKETPLACE_URL || '/api';

interface ApiError {
  error: string;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    method: string,
    path: string,
    data?: unknown
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const options: RequestInit = {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
    };

    if (data) {
      options.body = JSON.stringify(data);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const errorData = (await response.json()) as ApiError;
      throw new Error(errorData.error || `HTTP ${response.status}`);
    }

    return response.json() as Promise<T>;
  }

  // Tasks
  async createTask(
    principal_id: string,
    description: string
  ): Promise<Task> {
    const response = await this.request<TaskResponse>('POST', '/tasks', {
      principal_id,
      description,
    });
    return response.task;
  }

  async listTasks(skip: number = 0, limit: number = 50): Promise<{
    tasks: Task[];
    total: number;
  }> {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    const response = await this.request<TaskListResponse>(
      'GET',
      `/tasks?${params}`
    );
    return {
      tasks: response.tasks,
      total: response.total,
    };
  }

  async getTask(task_id: string): Promise<Task> {
    const response = await this.request<TaskResponse>('GET', `/tasks/${task_id}`);
    return response.task;
  }

  async acceptTask(task_id: string, worker_principal: string): Promise<Task> {
    const response = await this.request<TaskResponse>(
      'POST',
      `/tasks/${task_id}/accept`,
      { worker_principal }
    );
    return response.task;
  }

  // Negotiations
  async sendMessage(
    task_id: string,
    from_principal: string,
    message: string
  ): Promise<NegotiationMessage> {
    const response = await this.request<NegotiationResponse>(
      'POST',
      `/negotiations/${task_id}`,
      { from_principal, message }
    );
    return response.message;
  }

  async getNegotiations(task_id: string): Promise<Array<{
    from: string;
    message: string;
    timestamp: string;
  }>> {
    const response = await this.request<NegotiationsResponse>(
      'GET',
      `/negotiations/${task_id}`
    );
    return response.negotiations;
  }

  async completeTask(
    task_id: string,
    author_principal: string,
    outcome: string
  ): Promise<Task> {
    const response = await this.request<TaskResponse>(
      'POST',
      `/negotiations/${task_id}/complete`,
      { author_principal, outcome }
    );
    return response.task;
  }
}

export const apiClient = new ApiClient();

export interface NegotiationMessage {
  from: string;
  message: string;
  timestamp: string;
}

export default apiClient;
