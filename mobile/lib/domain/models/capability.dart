/// A named, versioned skill an agent claims to perform, e.g.
/// `terraform.generate`. Mirrors `schemas/capability.schema.json`.
class Capability {
  const Capability({
    required this.id,
    required this.version,
    required this.description,
  });

  final String id;
  final String version;
  final String description;

  factory Capability.fromJson(Map<String, dynamic> json) => Capability(
        id: json['id'] as String,
        version: json['version'] as String,
        description: json['description'] as String,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'version': version,
        'description': description,
      };
}
