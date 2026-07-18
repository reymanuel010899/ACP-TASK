import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:agenttrust_mobile/core/format.dart';
import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/theme/app_typography.dart';
import 'package:agenttrust_mobile/core/widgets/app_badge.dart';
import 'package:agenttrust_mobile/core/widgets/progress_stepper.dart';
import 'package:agenttrust_mobile/core/widgets/screen_header.dart';
import 'package:agenttrust_mobile/data/providers/app_providers.dart';
import 'package:agenttrust_mobile/domain/models/received_offer.dart';
import 'package:agenttrust_mobile/domain/models/task.dart';

class TaskProgressScreen extends ConsumerWidget {
  const TaskProgressScreen({required this.taskId, super.key});

  final String taskId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = AppTokens.of(context);
    final taskAsync = ref.watch(taskStreamProvider(taskId));

    return Scaffold(
      body: SafeArea(
        child: taskAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text('Error: $e')),
          data: (task) => ListView(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              AppSpacing.sm,
              AppSpacing.lg,
              40,
            ),
            children: [
              ScreenHeader(
                title: 'Tarea en curso',
                trailing: task.isTerminal
                    ? AppBadge(
                        label: 'VERIFICADA',
                        color: tokens.accentGreen,
                        icon: Icons.verified_user,
                      )
                    : AppBadge(
                        label: 'EN VIVO',
                        color: tokens.accentGreen,
                        icon: Icons.circle,
                      ),
              ),
              const SizedBox(height: AppSpacing.lg),

              _SummaryCard(task: task),
              const SizedBox(height: AppSpacing.xl),

              const SectionTitle('Progreso de la tarea'),
              const SizedBox(height: AppSpacing.lg),
              ProgressStepper(current: task.stage),
              const SizedBox(height: AppSpacing.xl),

              if (task.isTerminal)
                _VerifiedCard(task: task)
              else if (task.selectedOffer != null)
                _SelectedCard(offer: task.selectedOffer!, stage: task.stage)
              else
                _OffersSection(task: task, taskId: taskId, ref: ref),
            ],
          ),
        ),
      ),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.task});
  final Task task;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: tokens.card,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: tokens.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          AppBadge(label: task.capabilityId, color: tokens.accentPurple, mono: true),
          const SizedBox(height: AppSpacing.md),
          Text(task.description, style: Theme.of(context).textTheme.bodyMedium),
          const SizedBox(height: AppSpacing.md),
          Row(
            children: [
              Icon(Icons.payments_outlined, size: 14, color: tokens.textMuted),
              const SizedBox(width: AppSpacing.xs),
              Text(
                'Hasta ${Fmt.price(task.budget, currency: task.currency)}',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: tokens.textMuted),
              ),
              const Spacer(),
              Text(
                Fmt.ago(task.createdAt),
                style: Theme.of(context)
                    .textTheme
                    .labelSmall
                    ?.copyWith(color: tokens.textMuted),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _OffersSection extends StatelessWidget {
  const _OffersSection({
    required this.task,
    required this.taskId,
    required this.ref,
  });

  final Task task;
  final String taskId;
  final WidgetRef ref;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final offers = task.offersByPrice;

    if (offers.isEmpty) {
      return Row(
        children: [
          const SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.md),
          Text(
            'Buscando agentes que compitan por tu trabajo…',
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(color: tokens.textMuted),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            SectionTitle('Ofertas recibidas'),
            const SizedBox(width: AppSpacing.sm),
            AppBadge(label: '${offers.length}', color: tokens.accentPurple),
            const Spacer(),
            Text(
              'Ordenadas por precio',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: tokens.textMuted),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.md),
        for (var i = 0; i < offers.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.md),
            child: _OfferTile(
              offer: offers[i],
              cheapest: i == 0,
              onSelect: () => ref
                  .read(activeTaskControllerProvider.notifier)
                  .selectOffer(taskId, offers[i].providerPrincipalId),
            ),
          ),
      ],
    );
  }
}

class _OfferTile extends StatelessWidget {
  const _OfferTile({
    required this.offer,
    required this.cheapest,
    required this.onSelect,
  });

  final ReceivedOffer offer;
  final bool cheapest;
  final VoidCallback onSelect;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: tokens.card,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
          color: cheapest ? tokens.accentGreen : tokens.borderSubtle,
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  offer.providerName,
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 2),
                Text(
                  Fmt.price(offer.price, currency: offer.currency),
                  style: AppTypography.mono(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: cheapest ? tokens.accentGreen : null,
                  ),
                ),
              ],
            ),
          ),
          FilledButton(
            onPressed: onSelect,
            style: FilledButton.styleFrom(
              backgroundColor:
                  cheapest ? tokens.accentGreen : tokens.accentPurple,
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.sm,
              ),
            ),
            child: const Text('Seleccionar'),
          ),
        ],
      ),
    );
  }
}

class _SelectedCard extends StatelessWidget {
  const _SelectedCard({required this.offer, required this.stage});
  final ReceivedOffer offer;
  final TaskStage stage;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: tokens.card,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: tokens.accentPurple),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${offer.providerName} · ${Fmt.price(offer.price, currency: offer.currency)}',
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                Text(
                  stage == TaskStage.verifying
                      ? 'Verificando la evidencia de forma independiente…'
                      : 'Ejecutando la tarea…',
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: tokens.textMuted),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _VerifiedCard extends StatelessWidget {
  const _VerifiedCard({required this.task});
  final Task task;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final offer = task.selectedOffer;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        // ignore: deprecated_member_use
        color: tokens.accentGreen.withOpacity(0.10),
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: tokens.accentGreen),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.verified_user, color: tokens.accentGreen, size: 20),
              const SizedBox(width: AppSpacing.sm),
              Text(
                'Trabajo verificado',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(
            offer == null
                ? 'La evidencia pasó la verificación independiente.'
                : '${offer.providerName} entregó por '
                    '${Fmt.price(offer.price, currency: offer.currency)}. '
                    'Un verificador independiente validó la evidencia '
                    '(schema válido, tests en verde).',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ],
      ),
    );
  }
}
