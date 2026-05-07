{
  description = "Sekurvia MCP server for Hermes Agent — SearXNG search + trafilatura URL reader.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self, nixpkgs, flake-utils }:
    let
      perSystem = flake-utils.lib.eachDefaultSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          py = pkgs.python3Packages;

          sekurvia-mcp = py.buildPythonApplication {
            pname = "sekurvia-mcp";
            version = "0.3.1";
            pyproject = true;
            src = ./.;

            build-system = with py; [ hatchling ];

            dependencies = with py; [
              mcp
              httpx
              trafilatura
              pydantic
            ];

            nativeCheckInputs = with py; [
              pytestCheckHook
              pytest-asyncio
              respx
            ];

            # Run only the unit tests; pytestCheckHook discovers tests/ automatically.
            pytestFlagsArray = [ "-q" "tests" ];

            meta = with pkgs.lib; {
              description = "Hermes Agent MCP server for SearXNG-backed web search and trafilatura content extraction.";
              homepage = "https://github.com/xor-xe/Sekurvia";
              license = licenses.mit;
              mainProgram = "sekurvia-mcp";
              maintainers = [ ];
            };
          };
        in
        {
          packages = {
            inherit sekurvia-mcp;
            default = sekurvia-mcp;
          };

          apps.default = {
            type = "app";
            program = "${sekurvia-mcp}/bin/sekurvia-mcp";
          };

          devShells.default = pkgs.mkShell {
            packages = [
              pkgs.python3
              py.pip
              py.pytest
              py.pytest-asyncio
              py.respx
              py.ruff
            ];
            shellHook = ''
              echo "sekurvia-mcp dev shell — use 'pip install -e .[dev]' to set up a venv"
            '';
          };

          checks.tests = sekurvia-mcp;
        }
      );
    in
    perSystem
    // {
      nixosModules.default = import ./modules/nixos/sekurvia.nix;

      overlays.default = final: prev: {
        sekurvia-mcp = self.packages.${prev.stdenv.hostPlatform.system}.sekurvia-mcp;
      };
    };
}
