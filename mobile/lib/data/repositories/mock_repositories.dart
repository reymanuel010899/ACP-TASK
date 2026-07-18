import 'dart:async';

import 'package:agenttrust_mobile/data/fixtures/demo_fixtures.dart';
import 'package:agenttrust_mobile/data/repositories/repositories.dart';
import 'package:agenttrust_mobile/domain/models/agent_registration.dart';
import 'package:agenttrust_mobile/domain/models/agent_summary.dart';
import 'package:agenttrust_mobile/domain/models/chat_message.dart';
import 'package:agenttrust_mobile/domain/models/offer.dart';
import 'package:agenttrust_mobile/domain/models/received_offer.dart';
import 'package:agenttrust_mobile/domain/models/recent_activity.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';
import 'package:agenttrust_mobile/domain/models/task_draft.dart';
import 'package:agenttrust_mobile/domain/models/user_profile.dart';

/// Small helper: simulated network latency for a demo that feels alive.
Future<void> _latency([int ms = 450]) =>
    Future<void>.delayed(Duration(milliseconds: ms));

class MockRegistryRepository implements RegistryRepository {
  @override
  Future<List<AgentSummary>> search({
    String? capabilityId,
    double? minReputation,
  }) async {
    await _latency();
    return DemoFixtures.agents.where((a) {
      if (capabilityId != null &&
          capabilityId.isNotEmpty &&
          a.capabilityId != capabilityId) {
        return false;
      }
      if (minReputation != null) {
        final rate = a.verificationRate;
        // An explicit floor excludes neutral (null) and below-threshold agents.
        if (rate == null || rate < minReputation) return false;
      }
      return true;
    }).toList();
  }

  @override
  Future<List<AgentSummary>> featured() async {
    await _latency();
    return DemoFixtures.featured();
  }
}

class MockProfileRepository implements ProfileRepository {
  @override
  Future<UserProfile> currentUser() async {
    await _latency();
    return DemoFixtures.profile;
  }

  @override
  Future<List<RecentActivity>> recentActivity() async {
    await _latency();
    return DemoFixtures.recentActivity();
  }
}

class MockAgentRegistrationRepository implements AgentRegistrationRepository {
  final List<AgentSummary> _registered = [];

  @override
  Future<void> register(AgentRegistration registration) async {
    await _latency(700);
    // NOTE: minPrice (private reservation) is deliberately NOT persisted into
    // the outward-facing registered summary — only the public list price.
    for (final capabilityId in registration.capabilities) {
      _registered.add(
        AgentSummary(
          principalId: 'prin_${registration.name.hashCode.toUnsigned(32)}',
          displayName: registration.name,
          capabilityId: capabilityId,
          listPrice: registration.listPrice,
          currency: registration.currency,
          endpointUrl: registration.endpointUrl,
          reputation: DemoFixtures.featured().first.reputation,
        ),
      );
    }
  }

  @override
  Future<List<AgentSummary>> registered() async {
    await _latency();
    return List.unmodifiable(_registered);
  }
}

/// Drives a task through the trust lifecycle over time, streaming updates.
///
/// Flow: submit → published → searching (offers arrive one by one) → chat
/// (awaits the user's offer selection) → verifying → executing → verified.
class MockTaskRepository implements TaskRepository {
  final Map<String, Task> _tasks = {};
  final Map<String, StreamController<Task>> _controllers = {};
  int _seq = 0;

  StreamController<Task> _controllerFor(String id) =>
      _controllers.putIfAbsent(id, () => StreamController<Task>.broadcast());

  void _emit(Task task) {
    _tasks[task.id] = task;
    _controllerFor(task.id).add(task);
  }

  @override
  Future<Task> submit(TaskDraft draft) async {
    await _latency(300);
    final id = 'task_${++_seq}';
    final task = Task(
      id: id,
      capabilityId: draft.capabilityId,
      description: draft.description,
      budget: draft.budget,
      currency: draft.currency,
      minReputation: draft.minReputation,
      fanOut: draft.fanOut,
      stage: TaskStage.published,
      createdAt: DateTime.now(),
    );
    _tasks[id] = task;
    // Kick off the live progression without blocking submit().
    unawaited(_drive(id));
    return task;
  }

  Future<void> _drive(String id) async {
    await _latency(700);
    _emit(_tasks[id]!.copyWith(stage: TaskStage.searching));

    final received = <ReceivedOffer>[];
    for (final o in DemoFixtures.demoOffers) {
      await _latency(900);
      final current = _tasks[id];
      if (current == null) return; // task disposed
      received.add(
        ReceivedOffer(
          providerPrincipalId: o.principalId,
          providerName: o.name,
          offer: Offer(
            taskId: id,
            capabilityId: current.capabilityId,
            price: o.price,
            currency: current.currency,
          ),
        ),
      );
      _emit(current.copyWith(offers: List.of(received)));
    }

    await _latency(500);
    // Offers are in; move to chat and await the user's selection.
    _emit(_tasks[id]!.copyWith(stage: TaskStage.chat));
  }

  @override
  Future<void> selectOffer(String taskId, String providerPrincipalId) async {
    final task = _tasks[taskId];
    if (task == null) return;
    final chosen = task.offers.firstWhere(
      (o) => o.providerPrincipalId == providerPrincipalId,
      orElse: () => task.offersByPrice.first,
    );

    _emit(task.copyWith(stage: TaskStage.verifying, selectedOffer: chosen));
    await _latency(1100);
    _emit(_tasks[taskId]!.copyWith(stage: TaskStage.executing));
    await _latency(1300);
    _emit(_tasks[taskId]!.copyWith(outcome: TaskOutcome.verified));
  }

  @override
  Stream<Task> watch(String taskId) async* {
    final current = _tasks[taskId];
    if (current != null) yield current;
    yield* _controllerFor(taskId).stream;
  }

  @override
  List<ChatMessage> scriptedChat(String capabilityId) =>
      DemoFixtures.scriptedChat();
}
