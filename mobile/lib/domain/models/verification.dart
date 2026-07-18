/// A machine-checkable claim bundle produced when a capability is exercised.
/// Mirrors `schemas/evidence.schema.json`.
class Evidence {
  const Evidence({
    required this.evidenceId,
    required this.sessionId,
    required this.capabilityId,
    required this.schemaValid,
    required this.testsPassed,
    required this.artifactHashes,
  });

  final String evidenceId;
  final String sessionId;
  final String capabilityId;
  final bool schemaValid;
  final bool testsPassed;

  /// filename -> lowercase hex sha256.
  final Map<String, String> artifactHashes;

  factory Evidence.fromJson(Map<String, dynamic> json) => Evidence(
        evidenceId: json['evidence_id'] as String,
        sessionId: json['session_id'] as String,
        capabilityId: json['capability_id'] as String,
        schemaValid: json['schema_valid'] as bool,
        testsPassed: json['tests_passed'] as bool,
        artifactHashes:
            (json['artifact_hashes'] as Map).cast<String, String>(),
      );
}

enum Verdict { verified, rejected }

/// The outcome of an independent verifier checking one Evidence bundle.
/// Mirrors `schemas/verification-result.schema.json`.
class VerificationResult {
  const VerificationResult({
    required this.evidenceId,
    required this.principalId,
    required this.verdict,
    required this.reasoning,
    this.verifiedAt,
  });

  final String evidenceId;
  final String principalId;
  final Verdict verdict;
  final String reasoning;
  final DateTime? verifiedAt;

  factory VerificationResult.fromJson(Map<String, dynamic> json) =>
      VerificationResult(
        evidenceId: json['evidence_id'] as String,
        principalId: json['principal_id'] as String,
        verdict: (json['verdict'] as String) == 'verified'
            ? Verdict.verified
            : Verdict.rejected,
        reasoning: json['reasoning'] as String,
        verifiedAt: json['verified_at'] == null
            ? null
            : DateTime.parse(json['verified_at'] as String),
      );
}
