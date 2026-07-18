/// Aggregated verification history for one (Principal, Capability) pair.
/// Mirrors `schemas/reputation-record.schema.json`.
///
/// Neutral rule: a principal with zero completed tasks has counts 0 and
/// [verificationRate] == null (unknown), NEVER 0.0 (failed-by-default).
class ReputationRecord {
  const ReputationRecord({
    required this.principalId,
    required this.capabilityId,
    required this.tasksVerified,
    required this.tasksRejected,
    required this.verificationRate,
    required this.updatedAt,
  });

  final String principalId;
  final String capabilityId;
  final int tasksVerified;
  final int tasksRejected;

  /// tasks_verified / (verified + rejected), in [0, 1]. Null when both are 0.
  final double? verificationRate;
  final DateTime updatedAt;

  bool get isNeutral => tasksVerified == 0 && tasksRejected == 0;

  factory ReputationRecord.fromJson(Map<String, dynamic> json) {
    final rate = json['verification_rate'];
    return ReputationRecord(
      principalId: json['principal_id'] as String,
      capabilityId: json['capability_id'] as String,
      tasksVerified: json['tasks_verified'] as int,
      tasksRejected: json['tasks_rejected'] as int,
      verificationRate: rate == null ? null : (rate as num).toDouble(),
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );
  }

  Map<String, dynamic> toJson() => {
        'principal_id': principalId,
        'capability_id': capabilityId,
        'tasks_verified': tasksVerified,
        'tasks_rejected': tasksRejected,
        'verification_rate': verificationRate,
        'updated_at': updatedAt.toUtc().toIso8601String(),
      };
}
