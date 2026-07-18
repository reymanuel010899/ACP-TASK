import 'package:agenttrust_mobile/domain/models/agent_registration.dart';
import 'package:agenttrust_mobile/domain/models/agent_summary.dart';
import 'package:agenttrust_mobile/domain/models/chat_message.dart';
import 'package:agenttrust_mobile/domain/models/recent_activity.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';
import 'package:agenttrust_mobile/domain/models/task_draft.dart';
import 'package:agenttrust_mobile/domain/models/user_profile.dart';

/// Registry surface: capability search + featured agents.
/// Phase-2 HTTP impl backs these with the registry `GET /search` endpoint.
abstract interface class RegistryRepository {
  Future<List<AgentSummary>> search({
    String? capabilityId,
    double? minReputation,
  });

  /// Agents to feature on Home (a curated slice of the registry).
  Future<List<AgentSummary>> featured();
}

/// The signed-in operator's profile, stats, and recent activity.
abstract interface class ProfileRepository {
  Future<UserProfile> currentUser();
  Future<List<RecentActivity>> recentActivity();
}

/// Task lifecycle: submit a request, watch it progress live, select an offer.
///
/// [watch] returns a stream so a phase-2 HTTP impl can back it with
/// WebSocket/SSE/polling without any UI change.
abstract interface class TaskRepository {
  Future<Task> submit(TaskDraft draft);

  Stream<Task> watch(String taskId);

  /// Requester selects a competing offer; advances the task to completion.
  Future<void> selectOffer(String taskId, String providerPrincipalId);

  /// Scripted clarification dialogue seeded for a capability.
  List<ChatMessage> scriptedChat(String capabilityId);
}

/// Provider registration (the "Registrar Agente" flow). Mock stores locally.
abstract interface class AgentRegistrationRepository {
  Future<void> register(AgentRegistration registration);
  Future<List<AgentSummary>> registered();
}
