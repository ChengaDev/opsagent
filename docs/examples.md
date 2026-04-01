# GitHub Actions Examples

> **Tip:** Always use `set -o pipefail` before piping through `tee` — without it, the pipeline returns `tee`'s exit code (0) even when your command fails, so `if: failure()` never triggers.

## Python / pytest

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run tests
        run: |
          set -o pipefail
          pytest tests/ -v 2>&1 | tee "${{ runner.temp }}/pytest.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/pytest.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Node.js / npm

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install and build
        run: |
          npm ci
          set -o pipefail
          npm run build 2>&1 | tee "${{ runner.temp }}/build.log"

      - name: Run tests
        run: |
          set -o pipefail
          npm test 2>&1 | tee "${{ runner.temp }}/test.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Post RCA as a PR comment

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          github-token: ${{ secrets.GITHUB_TOKEN }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

OpsAgent posts the full RCA as a comment on the pull request that triggered the failure — no webhook configuration needed.

## Save the RCA to a file

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          output: ${{ runner.temp }}/rca.md
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Upload RCA report
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: rca-report
          path: ${{ runner.temp }}/rca.md
```

## Use a custom model

```yaml
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          model: claude-opus-4-6
          investigate-model: claude-haiku-4-5-20251001
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## Use a different provider

```yaml
      # Google Gemini
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          provider: google
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
```

```yaml
      # OpenAI
      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/test.log
          workspace: ${{ github.workspace }}
          provider: openai
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## CD pipeline — Helm deploy

```yaml
      - name: Deploy
        run: |
          set -o pipefail
          helm upgrade --install my-service ./charts/my-service \
            --namespace production \
            --set image.tag=${{ github.sha }} \
            --wait --timeout 5m 2>&1 | tee "${{ runner.temp }}/deploy.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/deploy.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
          webhook-url: ${{ secrets.WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## CD pipeline — Terraform

```yaml
      - name: Terraform apply
        run: |
          set -o pipefail
          terraform apply -auto-approve 2>&1 | tee "${{ runner.temp }}/tf.log"

      - name: Run OpsAgent RCA
        if: failure()
        uses: ChengaDev/opsagent@v1
        with:
          log-path: ${{ runner.temp }}/tf.log
          workspace: ${{ github.workspace }}
          slack-webhook: ${{ secrets.SLACK_WEBHOOK_URL }}
          webhook-url: ${{ secrets.WEBHOOK_URL }}
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

## GitLab CI

```yaml
rca:
  stage: .post
  when: on_failure
  script:
    - pip install "git+https://github.com/ChengaDev/opsagent.git[all-providers]"
    - opsagent --log-path build.log --workspace .
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

## Jenkins

```groovy
post {
  failure {
    sh '''
      pip install "git+https://github.com/ChengaDev/opsagent.git[all-providers]"
      opsagent --log-path build.log --workspace .
    '''
  }
}
```
