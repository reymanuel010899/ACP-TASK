import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:agenttrust_mobile/data/repositories/repositories.dart';
import 'package:agenttrust_mobile/domain/models/agent_summary.dart';
import 'package:agenttrust_mobile/domain/models/chat_message.dart';
import 'package:agenttrust_mobile/domain/models/recent_activity.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';
import 'package:agenttrust_mobile/domain/models/task_draft.dart';
import 'package:agenttrust_mobile/domain/models/user_profile.dart';

// ---------------------------------------------------------------------------
// Repository providers — throw by default, overridden in main.dart's
// ProviderScope with the Mock implementations. Swapping to real HTTP in
// phase 2 is a one-line override change here; nothing else in the app changes.
// ---------------------------------------------------------------------------

final registryRepositoryProvider = Provider<RegistryRepository>(
  (ref) => throw UnimplementedError('override registryRepositoryProvider'),
);

final profileRepositoryProvider = Provider<ProfileRepository>(
  (ref) => throw UnimplementedError('override profileRepositoryProvider'),
);

final taskRepositoryProvider = Provider<TaskRepository>(
  (ref) => throw UnimplementedError('override taskRepositoryProvider'),
);

final agentRegistrationRepositoryProvider =
    Provider<AgentRegistrationRepository>(
  (ref) =>
      throw UnimplementedError('override agentRegistrationRepositoryProvider'),
);

// ---------------------------------------------------------------------------
// Derived read providers
// ---------------------------------------------------------------------------

final userProfileProvider = FutureProvider<UserProfile>(
  (ref) => ref.watch(profileRepositoryProvider).currentUser(),
);

final recentActivityProvider = FutureProvider<List<RecentActivity>>(
  (ref) => ref.watch(profileRepositoryProvider).recentActivity(),
);

final featuredAgentsProvider = FutureProvider<List<AgentSummary>>(
  (ref) => ref.watch(registryRepositoryProvider).featured(),
);

/// Explore search parameters. A record so family caching gets value equality.
typedef AgentQuery = ({String? capabilityId, double? minReputation});

final agentSearchProvider =
    FutureProvider.family<List<AgentSummary>, AgentQuery>(
  (ref, query) => ref.watch(registryRepositoryProvider).search(
        capabilityId: query.capabilityId,
        minReputation: query.minReputation,
      ),
);

final chatScriptProvider = Provider.family<List<ChatMessage>, String>(
  (ref, capabilityId) =>
      ref.watch(taskRepositoryProvider).scriptedChat(capabilityId),
);

/// Live task lifecycle stream, keyed by task id.
final taskStreamProvider = StreamProvider.family<Task, String>(
  (ref, taskId) => ref.watch(taskRepositoryProvider).watch(taskId),
);

// ---------------------------------------------------------------------------
// Active task controller — holds the id of the task the user is tracking.
// ---------------------------------------------------------------------------

class ActiveTaskController extends Notifier<String?> {
  @override
  String? build() => null;

  Future<Task> submit(TaskDraft draft) async {
    final task = await ref.read(taskRepositoryProvider).submit(draft);
    state = task.id;
    return task;
  }

  Future<void> selectOffer(String taskId, String providerPrincipalId) =>
      ref.read(taskRepositoryProvider).selectOffer(taskId, providerPrincipalId);

  void clear() => state = null;
}

final activeTaskControllerProvider =
    NotifierProvider<ActiveTaskController, String?>(ActiveTaskController.new);
