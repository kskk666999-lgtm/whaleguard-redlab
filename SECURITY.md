# Security Policy

## Supported version

Security fixes target the current `main` branch until the first stable release establishes a version matrix.

## Reporting a vulnerability

Please do not disclose exploitable details in a public issue. Contact the maintainers through the private security reporting channel configured on the repository. Include the affected version, authorized reproduction conditions, impact, and a minimal non-destructive proof.

Never include real API keys, tokens, customer prompts, model outputs, cookies or personal data. Use fictional canaries and local mock targets.

## Safety boundary

WhaleGuard is limited to local, owned, or explicitly authorized targets. Reports that require C2, WebShells, credential theft, brute force, persistence, evasion, arbitrary Shell, unauthorized public scanning or automatic exploitation are outside project scope.

## Deployment

The default Compose file binds only Web/API to `127.0.0.1`; Mock services remain on a private Docker network. Before a team deployment, add TLS, an identity-aware reverse proxy, host firewall egress rules, backup procedures and secret rotation.
