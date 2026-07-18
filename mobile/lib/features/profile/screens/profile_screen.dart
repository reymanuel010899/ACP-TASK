import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:agenttrust_mobile/core/format.dart';
import 'package:agenttrust_mobile/core/router/app_router.dart';
import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/core/theme/app_typography.dart';
import 'package:agenttrust_mobile/core/widgets/screen_header.dart';
import 'package:agenttrust_mobile/core/widgets/stat_card.dart';
import 'package:agenttrust_mobile/data/providers/app_providers.dart';
import 'package:agenttrust_mobile/domain/models/user_profile.dart';

/// Profile has no Pencil design; this is an on-brand view of the operator's
/// principal, keys, headline stats, and advertised capabilities, with a
/// shortcut into the provider-registration flow.
class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokens = AppTokens.of(context);
    final profileAsync = ref.watch(userProfileProvider);

    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: profileAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text('Error: $e')),
          data: (profile) => ListView(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              AppSpacing.lg,
              AppSpacing.lg,
              120,
            ),
            children: [
              _Header(profile: profile),
              const SizedBox(height: AppSpacing.xl),

              Row(
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
                      value: Fmt.rate(profile.verificationRate),
                      label: 'Tasa de verificación',
                      icon: Icons.trending_up,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.xl),

              const SectionTitle('Identidad'),
              const SizedBox(height: AppSpacing.sm),
              _KeyRow(
                label: 'Principal',
                value: profile.principal.principalId,
              ),
              _KeyRow(
                label: 'Clave pública (ed25519)',
                value: _mask(profile.principal.publicKey),
              ),
              const SizedBox(height: AppSpacing.xl),

              const SectionTitle('Capacidades'),
              const SizedBox(height: AppSpacing.sm),
              Wrap(
                spacing: AppSpacing.sm,
                runSpacing: AppSpacing.sm,
                children: [
                  for (final c in profile.capabilities)
                    Chip(label: Text(c)),
                ],
              ),
              const SizedBox(height: AppSpacing.xl),

              OutlinedButton.icon(
                onPressed: () => context.push(AppRoutes.register),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('Registrar un agente proveedor'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _mask(String key) {
    if (key.length <= 12) return key;
    return '${key.substring(0, 8)}…${key.substring(key.length - 4)}';
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.profile});
  final UserProfile profile;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Row(
      children: [
        Container(
          width: 56,
          height: 56,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            // ignore: deprecated_member_use
            color: tokens.accentPurple.withOpacity(0.15),
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
          child: Text(
            profile.displayName.characters.first.toUpperCase(),
            style: AppTypography.mono(
              fontSize: 24,
              fontWeight: FontWeight.w700,
              color: tokens.accentPurple,
            ),
          ),
        ),
        const SizedBox(width: AppSpacing.lg),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                profile.displayName,
                style: Theme.of(context)
                    .textTheme
                    .headlineSmall
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              Text(
                'Operador · ${profile.activeCount} tareas en curso',
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: tokens.textMuted),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _KeyRow extends StatelessWidget {
  const _KeyRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: tokens.card,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: tokens.borderSubtle),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: tokens.textMuted),
            ),
          ),
          Text(value, style: AppTypography.mono(fontSize: 12)),
        ],
      ),
    );
  }
}
