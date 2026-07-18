import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'package:agenttrust_mobile/core/router/app_router.dart';
import 'package:agenttrust_mobile/core/theme/app_theme.dart';

/// Root widget. Dark-first Material 3 app driven by go_router.
class AgentTrustApp extends StatefulWidget {
  const AgentTrustApp({super.key});

  @override
  State<AgentTrustApp> createState() => _AgentTrustAppState();
}

class _AgentTrustAppState extends State<AgentTrustApp> {
  // Build the router once so navigation state survives rebuilds.
  late final GoRouter _router = buildRouter();

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'AgentTrust',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.dark(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.dark,
      routerConfig: _router,
    );
  }
}
