# Sekurvia NixOS module.
#
# Auto-wires the sekurvia-mcp stdio server into Hermes via nyxorn's
# `services.aiAgent.hermes.mcpServers` slot. Provides:
#
#   services.aiAgent.sekurvia.enable    – default: engine == "hermes"
#   services.aiAgent.sekurvia.package   – default: pkgs.sekurvia-mcp (overlay or self.packages)
#
# The module is intentionally additive — Hermes' auto-registered
# `mcp_searxng_*` toolset (when `services.aiAgent.enableSearxng = true`) keeps
# working alongside `mcp_sekurvia_*`. There is no name collision: server names
# differ, so tool prefixes differ.
#
# This module assumes the user is also importing nyxorn (so that
# `services.aiAgent.*` options exist). If you don't use nyxorn, configure
# Hermes' `mcpServers` directly with the path to the sekurvia-mcp binary.

{ config, lib, pkgs, ... }:

let
  agent = config.services.aiAgent or { };
  cfg = agent.sekurvia or { };
in
{
  options.services.aiAgent.sekurvia = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = (agent.enable or false) && (agent.engine or "openclaw") == "hermes";
      defaultText = lib.literalExpression
        ''services.aiAgent.enable && services.aiAgent.engine == "hermes"'';
      description = ''
        Wire the Sekurvia MCP server into Hermes' `mcpServers` slot under the
        key `sekurvia`, surfacing two tools to the agent:

          - `mcp_sekurvia_search` — SearXNG-backed web search.
          - `mcp_sekurvia_read`   — URL fetch + trafilatura main-content
            extraction.

        Coexists with Hermes' auto-registered `mcp_searxng_*` toolset (different
        server name → different tool prefix → no collision).

        Defaults to `true` when `services.aiAgent.engine = "hermes"`.
      '';
    };

    package = lib.mkOption {
      type = lib.types.package;
      default =
        if pkgs ? sekurvia-mcp
        then pkgs.sekurvia-mcp
        else throw ''
          services.aiAgent.sekurvia.package is unset and `pkgs.sekurvia-mcp`
          isn't in the current pkgs set.

          Either:
            - apply this flake's `overlays.default`, or
            - set `services.aiAgent.sekurvia.package` to
              `inputs.sekurvia.packages.''${pkgs.system}.sekurvia-mcp`.
        '';
      defaultText = lib.literalExpression "pkgs.sekurvia-mcp";
      description = ''
        The `sekurvia-mcp` package providing the stdio MCP server binary.
        Override to pin a specific revision or to swap the build (e.g.
        a uv2nix-built variant).
      '';
    };

    extraEnv = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = ''
        Extra environment variables passed to the MCP server process.
        `SEARXNG_URL` is supplied by nyxorn when
        `services.aiAgent.enableSearxng = true`, so you typically don't
        need to set anything here. Use this for `SEKURVIA_AUTH_TOKEN` or
        any of the `SEKURVIA_*` tuning variables.
      '';
      example = lib.literalExpression ''{
        SEKURVIA_MAX_RESULTS = "15";
        SEKURVIA_LANGUAGE    = "en";
      }'';
    };
  };

  config = lib.mkIf cfg.enable {
    services.aiAgent.hermes.mcpServers.sekurvia = {
      command = lib.getExe cfg.package;
      args = [ ];
      env = cfg.extraEnv;
    };
  };
}
