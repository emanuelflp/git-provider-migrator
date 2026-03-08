# GitLab to GitHub Repository Migrator

Um script Python para migrar repositórios do GitLab para o GitHub usando a API de importação do GitHub. O script verifica automaticamente se o repositório já existe no GitHub e o ignora caso exista.

## Funcionalidades

- ✅ Migra repositórios do GitLab para o GitHub usando a API oficial de importação
- ✅ Verifica se o repositório já existe no GitHub antes de migrar
- ✅ Ignora repositórios que já existem (não duplica)
- ✅ Suporta migração de repositórios privados e públicos
- ✅ Suporta migração em lote (múltiplos repositórios de uma vez)
- ✅ Aguarda e monitora o status da importação
- ✅ Logging detalhado de todo o processo
- ✅ Suporta organizações do GitHub

## Pré-requisitos

1. **Python 3.7+**

2. **Token do GitHub** (Personal Access Token - Classic) com as seguintes permissões:
   - `repo` - Full control of private repositories (inclui todas as permissões necessárias para criar e importar repos)
   
   **Como criar:**
   1. Acesse: https://github.com/settings/tokens
   2. Clique em "Generate new token" → "Generate new token (classic)"
   3. Dê um nome descritivo (ex: "GitLab Migration")
   4. Selecione o escopo `repo` (isso é suficiente para a importação)
   5. Clique em "Generate token" e copie o token gerado
   
   **Ou use Fine-grained token** com as seguintes permissões:
   - Repository permissions:
     - `Contents` - Read and write
     - `Metadata` - Read-only (obrigatório)
     - `Administration` - Read and write (para criar repositórios)

3. **Token do GitLab** (opcional, apenas para repositórios privados):
   - Crie em: https://gitlab.com/-/profile/personal_access_tokens
   - Permissão necessária: `read_repository`

## Instalação

```bash
cd gitlab-to-github-migrator

# Criar ambiente virtual (recomendado)
python3 -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt
```

## Configuração

### Variáveis de Ambiente (Recomendado)

```bash
export GITHUB_TOKEN="github_pat_xxxxxxxxxxxxxxxxxxxx"
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"  # Opcional, para repos privados
```

Ou crie um arquivo `.env`:

```bash
GITHUB_TOKEN=seu_token_github_aqui
GITLAB_TOKEN=seu_token_gitlab_aqui
```

## Uso

### Migrar um Único Repositório

```bash
python migrate.py \
  --github-token "seu_token_github" \
  --gitlab-token "seu_token_gitlab" \
  --gitlab-url "https://gitlab.com/username/repo.git" \
  --repo-name "nome-do-repo-no-github" \
  --description "Descrição do repositório" \
  --private
```

#### Exemplo Prático

```bash
# Repositório privado
python migrate.py \
  --gitlab-url "https://gitlab.com/myuser/my-project.git" \
  --repo-name "my-project" \
  --private

# Repositório público
python migrate.py \
  --gitlab-url "https://gitlab.com/myuser/public-project.git" \
  --repo-name "public-project" \
  --public
```

### Migrar Múltiplos Repositórios (Modo em Lote)

1. Crie um arquivo JSON com a lista de repositórios (veja `repositories.json.example`):

```json
[
  {
    "gitlab_url": "https://gitlab.com/username/repo1.git",
    "repo_name": "repo1",
    "private": true,
    "description": "Repositório 1 migrado do GitLab"
  },
  {
    "gitlab_url": "https://gitlab.com/username/repo2.git",
    "repo_name": "repo2",
    "private": false,
    "description": "Repositório 2 migrado do GitLab"
  }
]
```

2. Execute o script com o arquivo:

```bash
python migrate.py --batch-file repositories.json
```

### Migrar para uma Organização do GitHub

```bash
python migrate.py \
  --github-org "nome-da-organizacao" \
  --gitlab-url "https://gitlab.com/username/repo.git" \
  --repo-name "repo"
```

## Parâmetros

| Parâmetro | Descrição | Obrigatório |
|-----------|-----------|-------------|
| `--github-token` | Token de acesso pessoal do GitHub | Sim* |
| `--gitlab-token` | Token de acesso pessoal do GitLab | Não** |
| `--github-org` | Nome da organização do GitHub | Não |
| `--gitlab-url` | URL do repositório GitLab | Sim*** |
| `--repo-name` | Nome do repositório no GitHub | Sim*** |
| `--private` | Tornar o repositório privado (padrão) | Não |
| `--public` | Tornar o repositório público | Não |
| `--description` | Descrição do repositório | Não |
| `--batch-file` | Arquivo JSON com múltiplos repositórios | Não |
| `--no-wait` | Não aguardar a conclusão da importação | Não |

\* Pode ser fornecido via variável de ambiente `GITHUB_TOKEN`  
\** Necessário apenas para repositórios privados. Pode ser fornecido via `GITLAB_TOKEN`  
\*** Não necessário ao usar `--batch-file`

## Exemplos de Uso

### Exemplo 1: Migração Simples

```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
export GITLAB_TOKEN="glpat-xxxxxxxxxxxx"

python migrate.py \
  --gitlab-url "https://gitlab.com/mycompany/backend.git" \
  --repo-name "backend" \
  --description "Backend API migrado do GitLab"
```

### Exemplo 2: Migração em Lote

```bash
# Criar arquivo repositories.json
cat > repositories.json << 'EOF'
[
  {
    "gitlab_url": "https://gitlab.com/mycompany/frontend.git",
    "repo_name": "frontend",
    "private": true,
    "description": "Frontend application"
  },
  {
    "gitlab_url": "https://gitlab.com/mycompany/backend.git",
    "repo_name": "backend",
    "private": true,
    "description": "Backend API"
  },
  {
    "gitlab_url": "https://gitlab.com/mycompany/mobile.git",
    "repo_name": "mobile-app",
    "private": true,
    "description": "Mobile application"
  }
]
EOF

# Executar migração
python migrate.py --batch-file repositories.json
```

### Exemplo 3: Migração para Organização

```bash
python migrate.py \
  --github-org "my-organization" \
  --gitlab-url "https://gitlab.com/old-org/project.git" \
  --repo-name "project" \
  --private
```

### Exemplo 4: Migração sem Esperar

```bash
# Inicia a importação mas não espera a conclusão
python migrate.py \
  --gitlab-url "https://gitlab.com/user/large-repo.git" \
  --repo-name "large-repo" \
  --no-wait
```

## Como Funciona

1. **Verificação**: O script primeiro verifica se o repositório já existe no GitHub
2. **Criação**: Se não existir, cria um novo repositório no GitHub
3. **Importação**: Inicia o processo de importação usando a API do GitHub
4. **Monitoramento**: Acompanha o status da importação até a conclusão
5. **Relatório**: Exibe o resultado da migração (sucesso ou falha)

## Recursos da API do GitHub

O script utiliza a [GitHub Source Imports API](https://docs.github.com/en/rest/migrations/source-imports) que:

- Importa o histórico completo de commits
- Mantém branches e tags
- Preserva a estrutura do repositório
- Funciona com repositórios grandes

## Tratamento de Erros

O script trata automaticamente:

- ✅ Repositórios que já existem (ignora)
- ✅ Erros de autenticação
- ✅ Timeouts na importação
- ✅ Rate limiting da API
- ✅ URLs inválidas

## Limitações

- A API do GitHub tem limites de taxa (rate limits)
- Repositórios muito grandes podem demorar para importar
- Issues, Pull Requests e Wiki não são migrados (apenas o código)
- Para migrar issues e PRs, use o [GitHub Enterprise Importer](https://docs.github.com/en/migrations/using-github-enterprise-importer)

## Troubleshooting

### Erro de Autenticação

```
Failed to migrate: 401 Unauthorized
```

**Solução**: Verifique se seu token do GitHub está correto e tem as permissões necessárias.

### Repositório Já Existe

```
Repository already exists - skipping
```

**Solução**: Isso é esperado. O script ignora repositórios existentes por design.

### Timeout na Importação

```
Import timed out for repo-name
```

**Solução**: Repositórios grandes podem demorar mais. Use `--no-wait` e verifique o status manualmente no GitHub.

## Logs

O script gera logs detalhados com:
- Timestamp de cada operação
- Status de cada repositório
- Erros e avisos
- Resumo final da migração

## Segurança

⚠️ **IMPORTANTE**:
- Nunca commit seus tokens no Git
- Use variáveis de ambiente para tokens
- Mantenha o arquivo `.env` no `.gitignore`
- Considere usar GitHub Secrets para CI/CD

## Contribuindo

Sinta-se à vontade para abrir issues ou pull requests para melhorias.

## Licença

MIT License - use livremente para seus projetos.

## Recursos Adicionais

- [GitHub REST API - Source Imports](https://docs.github.com/en/rest/migrations/source-imports)
- [Criar Token do GitHub](https://github.com/settings/tokens)
- [Criar Token do GitLab](https://gitlab.com/-/profile/personal_access_tokens)
- [GitHub Enterprise Importer](https://docs.github.com/en/migrations/using-github-enterprise-importer)

---

Desenvolvido com ❤️ para facilitar migrações do GitLab para o GitHub
