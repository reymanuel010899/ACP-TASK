import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:agenttrust_mobile/core/format.dart';
import 'package:agenttrust_mobile/core/router/app_router.dart';
import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/widgets/agent_card.dart';
import 'package:agenttrust_mobile/core/widgets/screen_header.dart';
import 'package:agenttrust_mobile/core/widgets/stat_card.dart';
import 'package:agenttrust_mobile/data/providers/app_providers.dart';
import 'package:agenttrust_mobile/domain/models/recent_activity.dart';
import 'package:agenttrust_mobile/features/home/widgets/active_task_banner.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(userProfileProvider);
    final featuredAsync = ref.watch(featuredAgentsProvider);
    final activityAsync = ref.watch(recentActivityProvider);
    final activeTaskId = ref.watch(activeTaskControllerProvider);
    final tokens = AppTokens.of(context);

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.lg,
            AppSpacing.lg,
            120,
          ),
          children: [
            // Greeting
            profileAsync.when(
              loading: () => const _GreetingSkeleton(),
              error: (e, _) => Text('Error: $e'),
              data: (profile) => Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Bienvenido de vuelta',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(color: tokens.textMuted),
                        ),
                        Text(
                          profile.displayName,
                          style: Theme.of(context)
                              .textTheme
                              .headlineSmall
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: () {},
                    icon: const Icon(Icons.notifications_outlined),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.lg),

            // Active task banner (only when a task is being tracked)
            if (activeTaskId != null) ...[
              _ActiveTask(taskId: activeTaskId),
              const SizedBox(height: AppSpacing.lg),
            ],

            // Stats
            profileAsync.maybeWhen(
              orElse: () => const SizedBox.shrink(),
              data: (profile) => Row(
                children: [
                  Expanded(
                    child: StatCard(
                      value: '${profile.verifiedCount}',
                      label: 'Verificadas',
                      icon: Icons.verified_user_outlined,
                      accent: tokens.accentGreen,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: StatCard(
                      value: '${profile.activeCount}',
                      label: 'En curso',
                      icon: Icons.bolt_outlined,
                      accent: tokens.accentCyan,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: StatCard(
                      value: Fmt.rate(profile.verificationRate),
                      label: 'Tasa',
                      icon: Icons.trending_up,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.lg),

            // CTA
            _RequestCta(onTap: () => context.go(AppRoutes.request)),
            const SizedBox(height: AppSpacing.xl),

            // Featured agents
            const SectionTitle('Agentes destacados'),
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              height: 148,
              child: featuredAsync.when(
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => Text('Error: $e'),
                data: (agents) => ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: agents.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(width: AppSpacing.md),
                  itemBuilder: (context, i) => AgentCard(
                    agent: agents[i],
                    width: 280,
                  ),
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.xl),

            // Recent activity
            const SectionTitle('Actividad reciente'),
            const SizedBox(height: AppSpacing.sm),
            activityAsync.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Text('Error: $e'),
              data: (items) => Column(
                children: [
                  for (final item in items) _ActivityTile(item: item),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActiveTask extends ConsumerWidget {
  const _ActiveTask({required this.taskId});
  final String taskId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final taskAsync = ref.watch(taskStreamProvider(taskId));
    return taskAsync.maybeWhen(
      orElse: () => const SizedBox.shrink(),
      data: (task) => ActiveTaskBanner(
        task: task,
        onTap: () => context.push(AppRoutes.task(task.id)),
      ),
    );
  }
}

class _RequestCta extends StatelessWidget {
  const _RequestCta({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            // ignore: deprecated_member_use
            tokens.accentPurple.withOpacity(0.18),
            // ignore: deprecated_member_use
            tokens.accentCyan.withOpacity(0.10),
          ],
        ),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: tokens.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Solicita una tarea',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            'Encuentra agentes verificados que compiten por tu trabajo, '
            'al mejor precio.',
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(color: tokens.textMuted),
          ),
          const SizedBox(height: AppSpacing.md),
          FilledButton.icon(
            onPressed: onTap,
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Nueva Solicitud'),
          ),
        ],
      ),
    );
  }
}

class _ActivityTile extends StatelessWidget {
  const _ActivityTile({required this.item});
  final RecentActivity item;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final (icon, color) = switch (item.kind) {
      ActivityKind.taskVerified => (Icons.verified_user, tokens.accentGreen),
      ActivityKind.taskRejected => (Icons.cancel_outlined, tokens.accentPink),
      ActivityKind.reputationUpdated => (Icons.trending_up, tokens.accentCyan),
      ActivityKind.offerReceived => (Icons.local_offer_outlined, tokens.accentPurple),
    };

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        children: [
          Container(
            width: 34,
            height: 34,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              // ignore: deprecated_member_use
              color: color.withOpacity(0.14),
              borderRadius: BorderRadius.circular(AppRadius.sm),
            ),
            child: Icon(icon, size: 16, color: color),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.agentName,
                  style: Theme.of(context)
                      .textTheme
                      .bodyMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                Text(
                  item.detail,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: tokens.textMuted),
                ),
              ],
            ),
          ),
          Text(
            Fmt.ago(item.timestamp),
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: tokens.textMuted),
          ),
        ],
      ),
    );
  }
}

class _GreetingSkeleton extends StatelessWidget {
  const _GreetingSkeleton();
  @override
  Widget build(BuildContext context) => const SizedBox(
        height: 48,
        child: Center(child: CircularProgressIndicator()),
      );
}
