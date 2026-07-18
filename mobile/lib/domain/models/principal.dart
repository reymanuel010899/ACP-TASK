/// A long-lived cryptographic identity (agent, operator, or verifier).
/// Mirrors `schemas/principal.schema.json`.
class Principal {
  const Principal({
    required this.principalId,
    required this.publicKey,
    this.keyAlgorithm = 'ed25519',
    this.displayName,
  });

  final String principalId;

  /// Raw 32-byte ed25519 public key, base64 (44 chars).
  final String publicKey;
  final String keyAlgorithm;
  final String? displayName;

  factory Principal.fromJson(Map<String, dynamic> json) => Principal(
        principalId: json['principal_id'] as String,
        publicKey: json['public_key'] as String,
        keyAlgorithm: (json['key_algorithm'] as String?) ?? 'ed25519',
        displayName: json['display_name'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'principal_id': principalId,
        'public_key': publicKey,
        'key_algorithm': keyAlgorithm,
        if (displayName != null) 'display_name': displayName,
      };
}
