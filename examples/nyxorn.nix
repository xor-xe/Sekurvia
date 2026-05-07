# Drop-in nyxorn host config for the Sekurvia MCP server.
#
# This mirrors the working dotfiles shape so you can paste it into your
# system module with minimal diff. Two pieces matter:
#
#   1. Import `inputs.sekurvia.nixosModules.default` so
#      `services.aiAgent.sekurvia.*` options exist.
#   2. Apply `inputs.sekurvia.overlays.default` so `pkgs.sekurvia-mcp` is
#      available — that's what `services.aiAgent.sekurvia.package`
#      defaults to.
#
# Everything else is identical to a vanilla nyxorn host. The skill stays
# pinned at the same path so existing slash commands and config keys
# don't change.

# ---------------- flake.nix (system flake) ----------------
#
# {
#   inputs = {
#     nixpkgs.url     = "github:NixOS/nixpkgs/nixos-unstable";
#     nyxorn.url      = "github:xor-xe/nyxorn";
#     sekurvia.url    = "github:xor-xe/Sekurvia";
#
#     # Optional: keep Sekurvia's nixpkgs aligned with your system's, so
#     # `pkgs.python3Packages.mcp` etc. resolve from a single tree.
#     sekurvia.inputs.nixpkgs.follows = "nixpkgs";
#   };
#
#   outputs = inputs@{ nixpkgs, nyxorn, sekurvia, ... }: {
#     nixosConfigurations.yourhost = nixpkgs.lib.nixosSystem {
#       system = "x86_64-linux";
#       specialArgs = { inherit inputs; };
#       modules = [
#         nyxorn.nixosModules.default
#         sekurvia.nixosModules.default
#         ./host.nix
#       ];
#     };
#   };
# }

# ---------------- host.nix (your system module) ----------------

{ config, pkgs, inputs, ... }:

{
  nixpkgs.overlays = [ inputs.sekurvia.overlays.default ];

  services.aiAgent = {
    enable          = true;
    engine          = "hermes";
    gpuAcceleration = "cuda";

    # Local SearXNG on 127.0.0.1:8888. The Sekurvia NixOS module reads
    # `services.aiAgent.searxng.url` and injects it as SEARXNG_URL on the
    # MCP child process explicitly — Hermes' MCP launcher doesn't propagate
    # the gateway's own env, so this extra step is necessary. Override
    # via `services.aiAgent.sekurvia.searxngUrl` for a remote SearXNG.
    enableSearxng        = true;
    searxng.secretKey    = "<openssl rand -hex 32>";

    prePullModels = [
      "llama3.2"
      "qwen3.6:35b"
      "gemma4:26b"
      "gpt-oss:20b"
    ];
    ollama.channel = "master";
    defaultModel   = "gpt-oss:20b";

    # Skill body (markdown, ~65 lines) — routes the model to
    # mcp_sekurvia_search / mcp_sekurvia_read.
    hermes.skills."research/searxng-search" =
      inputs.sekurvia + "/searxng-search";

    # The actual MCP tools. Default `enable` is true when
    # engine == "hermes", so this block is mostly for visibility;
    # you only need to set anything if you want to override.
    sekurvia = {
      enable  = true;
      package = pkgs.sekurvia-mcp;
      # Optional knobs — leave empty to use the bundled defaults.
      extraEnv = {
        # SEKURVIA_MAX_RESULTS = "15";
        # SEKURVIA_LANGUAGE    = "en";
      };
    };

    hermes.environmentFiles = [ "/etc/hermes-telegram.env" ];

    hermes.settings = {
      toolsets               = [ "all" ];
      memory.memory_enabled  = true;
    };
  };
}

# ---------------- After rebuild ----------------
#
#   sudo nixos-rebuild switch --flake .#yourhost
#   nyxorn-status                # confirm hermes-agent + searxng up
#
# Then in a Hermes session:
#
#   /searxng-search what is the latest news on AI agents
#
# The model should pick `mcp_sekurvia_search` (declared schema, assertive
# description), then optionally `mcp_sekurvia_read` on a result URL, then
# answer with citations. If it instead reaches for the Hermes built-in
# `mcp_searxng_*`, that's also fine — both work; the Sekurvia tools are
# preferred for the richer schema and trafilatura-cleaned output.
