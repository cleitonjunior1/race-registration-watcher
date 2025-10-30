name: Monitorar inscrições (Mendoza/Patagonian)

on:
  schedule:
    - cron: "0 */6 * * *"
  workflow_dispatch:

permissions:
  contents: read
  actions: read

jobs:
  watch:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      # SOLUÇÃO A: detecção + download condicional
      - name: Verificar se existe artifact de estado
        id: find_artifact
        uses: actions/github-script@v7
        with:
          script: |
            const { data } = await github.rest.actions.listArtifactsForRepo({
              owner: context.repo.owner,
              repo: context.repo.repo,
              per_page: 100
            });
            const found = data.artifacts
              .filter(a => a.name === 'alert-state' && !a.expired)
              .sort((a,b) => new Date(b.created_at) - new Date(a.created_at))[0];
            core.setOutput('found', found ? 'true' : 'false');

      - name: Baixar estado anterior
        if: ${{ steps.find_artifact.outputs.found == 'true' }}
        uses: actions/download-artifact@v4
        with:
          name: alert-state
          path: .state

      # ... (demais passos: setup Python, executar checagem, upload do estado, e-mail, etc.)
``
