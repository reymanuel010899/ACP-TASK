import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import 'package:agenttrust_mobile/core/widgets/glass_nav_bar.dart';
import 'package:agenttrust_mobile/features/agents/screens/explore_screen.dart';
import 'package:agenttrust_mobile/features/agents/screens/register_agent_screen.dart';
import 'package:agenttrust_mobile/features/home/screens/home_screen.dart';
import 'package:agenttrust_mobile/features/profile/screens/profile_screen.dart';
import 'package:agenttrust_mobile/features/request/screens/task_progress_screen.dart';
import 'package:agenttrust_mobile/features/request/screens/task_request_screen.dart';

/// Stable route paths.
abstract final class AppRoutes {
  static const home = '/home';
  static const explore = '/explore';
  static const request = '/request';
  static const profile = '/profile';
  static const register = '/register';

  /// Task progress by id, e.g. `/task/task_1`.
  static String task(String id) => '/task/$id';
}

/// The app router. A stateful shell keeps each tab's own navigation stack and
/// scroll/form state; detail/flow screens (register, task progress) are pushed
/// above the shell so they cover the tab bar.
GoRouter buildRouter() {
  return GoRouter(
    initialLocation: AppRoutes.home,
    routes: [
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) =>
            RootShell(navigationShell: navigationShell),
        branches: [
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.home,
                builder: (context, state) => const HomeScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.explore,
                builder: (context, state) => const ExploreScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.request,
                builder: (context, state) => const TaskRequestScreen(),
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: AppRoutes.profile,
                builder: (context, state) => const ProfileScreen(),
              ),
            ],
          ),
        ],
      ),
      GoRoute(
        path: AppRoutes.register,
        parentNavigatorKey: rootNavigatorKey,
        builder: (context, state) => const RegisterAgentScreen(),
      ),
      GoRoute(
        path: '/task/:id',
        parentNavigatorKey: rootNavigatorKey,
        builder: (context, state) =>
            TaskProgressScreen(taskId: state.pathParameters['id']!),
      ),
    ],
    navigatorKey: rootNavigatorKey,
  );
}

final rootNavigatorKey = GlobalKey<NavigatorState>();

/// The shell scaffold hosting the four tabs and the frosted bottom nav bar.
class RootShell extends StatelessWidget {
  const RootShell({required this.navigationShell, super.key});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      extendBody: true,
      body: navigationShell,
      bottomNavigationBar: GlassNavBar(
        currentIndex: navigationShell.currentIndex,
        onTap: (index) => navigationShell.goBranch(
          index,
          initialLocation: index == navigationShell.currentIndex,
        ),
      ),
    );
  }
}
