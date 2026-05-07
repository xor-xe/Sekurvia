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

  # Hermes' MCP launcher does NOT propagate the gateway process's environment
  # to MCP child subprocesses, so even though nyxorn sets SEARXNG_URL on the
  # Hermes service, both `mcp_searxng_*` and `mcp_sekurvia_*` get spawned
  # without it and fail with "SEARXNG_URL not set". We work around this by
  # reading nyxorn's `services.aiAgent.searxng.url` (which exists when
  # `enableSearxng = true` and defaults to http://127.0.0.1:8888) and
  # injecting it explicitly into `mcpServers.sekurvia.env`.
  inheritedSearxngUrl =
    if (agent.enableSearxng or false)
    then lib.attrByPath [ "searxng" "url" ] "http://127.0.0.1:8888" agent
    else null;

  finalSearxngUrl =
    if cfg.searxngUrl != null then cfg.searxngUrl else inheritedSearxngUrl;

  derivedEnv =
    lib.optionalAttrs (finalSearxngUrl != null) { SEARXNG_URL = finalSearxngUrl; };

  # extraEnv wins on conflict — explicit user override beats the derived default.
  mergedEnv = derivedEnv // cfg.extraEnv;
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

    searxngUrl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      defaultText = lib.literalExpression
        ''config.services.aiAgent.searxng.url, or null when enableSearxng = false'';
      description = ''
        URL of the SearXNG instance the MCP server should query. Passed to
        the child process as the `SEARXNG_URL` environment variable.

        When left `null` (the default) and
        `services.aiAgent.enableSearxng = true`, this is auto-derived from
        nyxorn's `services.aiAgent.searxng.url`
        (which itself defaults to `http://127.0.0.1:8888`).

        Set explicitly when:
          - You run SearXNG on a different host or port.
          - You don't use nyxorn's `enableSearxng` and host SearXNG yourself.
      '';
      example = "http://searxng.internal.lan:8888";
    };

    extraEnv = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = ''
        Extra environment variables passed to the MCP server process.

        `SEARXNG_URL` is auto-derived from `services.aiAgent.searxng.url`
        when `enableSearxng = true`; you only need to set it here if you
        want to override that derivation. Use this option for
        `SEKURVIA_AUTH_TOKEN` or any of the `SEKURVIA_*` tuning variables.

        Anything set here wins over the auto-derived `SEARXNG_URL`.
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
      env = mergedEnv;
    };
  };
}
