import 'package:agenttrust_mobile/domain/models/reputation_record.dart';

/// A registry search result: a provider principal, the capability being
/// offered, its public price, and the per-capability reputation slice.
///
/// Corresponds to one entry of the registry `GET /search` response
/// (`{principal_id, agent_card, reputation_summary}`), flattened for the UI.
class AgentSummary {
  const AgentSummary({
    required this.principalId,
    required this.displayName,
    required this.capabilityId,
    required this.listPrice,
    required this.currency,
    required this.reputation,
    this.endpointUrl,
  });

  final String principalId;
  final String displayName;
  final String capabilityId;
  final double listPrice;
  final String currency;
  final ReputationRecord reputation;
  final String? endpointUrl;

  double? get verificationRate => reputation.verificationRate;
  int get tasksDone => reputation.tasksVerified + reputation.tasksRejected;

  factory AgentSummary.fromSearchCandidate(Map<String, dynamic> json) {
    final card = (json['agent_card'] as Map?)?.cast<String, dynamic>() ?? {};
    final rep = (json['reputation_summary'] as Map).cast<String, dynamic>();
    return AgentSummary(
      principalId: json['principal_id'] as String,
      displayName: (card['name'] as String?) ?? json['principal_id'] as String,
      capabilityId: rep['capability_id'] as String,
      listPrice: (card['list_price'] as num?)?.toDouble() ?? 0,
      currency: (card['currency'] as String?) ?? 'USD',
      endpointUrl: card['url'] as String?,
      reputation: ReputationRecord(
        principalId: json['principal_id'] as String,
        capabilityId: rep['capability_id'] as String,
        tasksVerified: (rep['tasks_verified'] as int?) ?? 0,
        tasksRejected: (rep['tasks_rejected'] as int?) ?? 0,
        verificationRate: (rep['verification_rate'] as num?)?.toDouble(),
        updatedAt: DateTime.now(),
      ),
    );
  }
}
