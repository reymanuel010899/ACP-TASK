import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:agenttrust_mobile/app.dart';
import 'package:agenttrust_mobile/data/providers/app_providers.dart';
import 'package:agenttrust_mobile/data/repositories/mock_repositories.dart';

void main() {
  runApp(
    ProviderScope(
      // Mock-first: the repository providers throw by default and are wired to
      // the Mock implementations here. Phase 2 swaps these overrides for the
      // Http* implementations — nothing else in the app changes.
      overrides: [
        registryRepositoryProvider
            .overrideWithValue(MockRegistryRepository()),
        profileRepositoryProvider.overrideWithValue(MockProfileRepository()),
        taskRepositoryProvider.overrideWithValue(MockTaskRepository()),
        agentRegistrationRepositoryProvider
            .overrideWithValue(MockAgentRegistrationRepository()),
      ],
      child: const AgentTrustApp(),
    ),
  );
}
