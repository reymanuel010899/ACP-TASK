import 'package:flutter/material.dart';

import 'package:agenttrust_mobile/core/theme/app_dimens.dart';
import 'package:agenttrust_mobile/core/theme/app_tokens.dart';
import 'package:agenttrust_mobile/domain/models/chat_message.dart';

/// "Chat con el agente" — the scripted clarification dialogue. In the mock,
/// user replies are appended locally and do not drive the flow.
class ChatPanel extends StatelessWidget {
  const ChatPanel({required this.messages, super.key});

  final List<ChatMessage> messages;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: tokens.input,
        borderRadius: BorderRadius.circular(AppRadius.lg),
        border: Border.all(color: tokens.borderSubtle),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.chat_bubble_outline,
                  size: 15, color: tokens.accentPurple),
              const SizedBox(width: AppSpacing.sm),
              Text(
                'Chat con el agente',
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          for (final m in messages) _Bubble(message: m),
        ],
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message});
  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final tokens = AppTokens.of(context);
    final isUser = message.role == ChatRole.user;
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: AppSpacing.sm),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width * 0.72,
        ),
        decoration: BoxDecoration(
          color: isUser ? tokens.accentPurple : tokens.card,
          borderRadius: BorderRadius.circular(AppRadius.md),
          border: Border.all(
            color: isUser ? tokens.accentPurple : tokens.borderSubtle,
          ),
        ),
        child: Text(
          message.text,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: isUser ? Colors.white : null,
              ),
        ),
      ),
    );
  }
}
