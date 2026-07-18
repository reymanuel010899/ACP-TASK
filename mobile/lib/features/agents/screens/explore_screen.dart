import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:agenttrust_mobile/core/router/app_router.dart';
import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/widgets/agent_card.dart';
import 'package:agenttrust_mobile/data/providers/app_providers.dart';

/// Explore has no Pencil design; this is an on-brand registry browser built
/// from the design system: capability filter + min-reputation toggle over the
/// mock registry search.
class ExploreScreen extends ConsumerStatefulWidget {
  const ExploreScreen({super.key});

  @override
  ConsumerState<ExploreScreen> createState() => _ExploreScreenState();
}

class _ExploreScreenState extends ConsumerState<ExploreScreen> {
  static const _capabilities = <String?>[
    null,
    'terraform.generate',
    'data.pipeline',
    'code.review',
  ];

  String? _capability;
  bool _provenOnly = false;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final query = (
      capabilityId: _capability,
      minReputation: _provenOnly ? 0.7 : null,
    );
    final resultsAsync = ref.watch(agentSearchProvider(query));

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
            Text(
              'Explorar agentes',
              style: Theme.of(context)
                  .textTheme
                  .headlineSmall
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            Text(
              'Busca en el registry por capacidad y reputación.',
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(color: tokens.textMuted),
            ),
            const SizedBox(height: AppSpacing.lg),

            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final cap in _capabilities)
                    Padding(
                      padding: const EdgeInsets.only(right: AppSpacing.sm),
                      child: ChoiceChip(
                        label: Text(cap ?? 'Todas'),
                        selected: _capability == cap,
                        onSelected: (_) => setState(() => _capability = cap),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: Text(
                'Solo probados (≥ 70%)',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              subtitle: Text(
                'Excluye agentes neutrales sin historial.',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: tokens.textMuted),
              ),
              value: _provenOnly,
              onChanged: (v) => setState(() => _provenOnly = v),
            ),
            const SizedBox(height: AppSpacing.sm),

            resultsAsync.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(AppSpacing.xl),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => Text('Error: $e'),
              data: (agents) => agents.isEmpty
                  ? Padding(
                      padding: const EdgeInsets.all(AppSpacing.xl),
                      child: Center(
                        child: Text(
                          'Ningún agente coincide con el filtro.',
                          style: Theme.of(context)
                              .textTheme
                              .bodyMedium
                              ?.copyWith(color: tokens.textMuted),
                        ),
                      ),
                    )
                  : Column(
                      children: [
                        for (final agent in agents)
                          Padding(
                            padding:
                                const EdgeInsets.only(bottom: AppSpacing.md),
                            child: AgentCard(
                              agent: agent,
                              onTap: () => context.go(AppRoutes.request),
                            ),
                          ),
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
