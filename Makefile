# Makefile do AVO Data Lab — a interface curta para as tarefas que se repetem.
#
# Regra de ouro deste arquivo: TODA receita roda da raiz do repositorio, sempre.
# Nao e estilo, e uma correcao de bug. `avo submit` resolve o alvo por
# Path.cwd()/targets e resolve o run por caminho relativo; rodado de dentro de
# runs/<id>/work/ ele nao acha nem um nem outro e falha com uma mensagem que
# nao explica nada (a "Falha 3" do historico do laboratorio). Por isso todo
# alvo abaixo faz `cd $(ROOT)` explicito, mesmo quando o make ja estaria la:
# assim `make -f /caminho/Makefile submit` funciona de qualquer diretorio,
# inclusive de dentro de um run dir.
#
# Veja o alvo `submit`: ele e a forma certa de submeter, embrulhada.

ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
PY ?= python3
TARGET ?= etl_agg
STEPS ?= 40
RUN ?=
M ?=

# Um alvo por linha, descoberto por varredura: um alvo novo entra em `make
# selftest` no instante em que ganha um target.yaml, sem editar este arquivo.
TARGETS := $(sort $(notdir $(patsubst %/target.yaml,%,$(wildcard $(ROOT)/targets/*/target.yaml))))

.DEFAULT_GOAL := help
.PHONY: help setup data test test-fast lint fmt selftest budget verify run submit status clean clean-data

## help: lista os alvos disponiveis (padrao)
help:
	@echo "AVO Data Lab — make <alvo>"
	@echo
	@sed -n 's/^## //p' $(lastword $(MAKEFILE_LIST)) | awk -F': ' '{printf "  %-14s %s\n", $$1, $$2}'
	@echo
	@echo "Alvos do laboratorio: $(TARGETS)"
	@echo
	@echo "Variaveis: TARGET=<alvo> (padrao $(TARGET))  STEPS=<n> (padrao $(STEPS))"
	@echo "           RUN=runs/<id>  M=\"resumo do passo\"  PY=$(PY)"
	@echo
	@echo "Atencao: 'avo submit' precisa rodar da RAIZ e com --run runs/<id>."
	@echo "         De dentro do run dir ele falha. Use 'make submit' — ele faz certo."

## setup: bootstrap completo (harness no commit fixado, install, datasets, gate)
setup:
	@cd $(ROOT) && ./bootstrap.sh

## data: gera os datasets congelados de todos os alvos (idempotente)
data:
	@cd $(ROOT) && for t in $(TARGETS); do \
		echo "==> $$t"; $(PY) targets/$$t/make_data.py || exit 1; \
	done

## test: suite completa, incluindo os testes lentos que medem tempo
test:
	@cd $(ROOT) && $(PY) -m pytest

## test-fast: so os testes rapidos (pula os marcados como slow)
test-fast:
	@cd $(ROOT) && $(PY) -m pytest -m "not slow"

# `examples/` guarda o registro congelado de um run de verdade: o codigo ali e o
# que o agente produziu, byte a byte, e reformata-lo falsificaria o registro que
# o diretorio existe para preservar. Por isso ele sai do FORMATADOR — e so dele.
# O `ruff check` continua valendo em tudo: import morto e variavel nao usada sao
# defeito mesmo num artefato.
SEM_FORMATADOR := --exclude examples

## lint: ruff check + ruff format --check (o que o CI cobra)
lint:
	@cd $(ROOT) && ruff check . && ruff format --check $(SEM_FORMATADOR) .

## fmt: aplica o ruff format e as correcoes automaticas do ruff check
fmt:
	@cd $(ROOT) && ruff check --fix . && ruff format $(SEM_FORMATADOR) .

## selftest: o gate de cada alvo contra seus mutantes — a checagem que mais importa
selftest:
	@cd $(ROOT) && falhou=""; for t in $(TARGETS); do \
		printf '==> %s\n' "$$t"; \
		$(PY) targets/$$t/eval.py --selftest || falhou="$$falhou $$t"; \
	done; \
	if [ -n "$$falhou" ]; then \
		echo; echo "GATE FUROU EM:$$falhou"; \
		echo "Um alvo sem --selftest verde nao entra e nao roda: sem gate, otimizacao e"; \
		echo "indistinguivel de reward hacking."; \
		exit 1; \
	fi

## budget: confere o dimensionamento do custo de avaliacao (teto e piso)
budget:
	@cd $(ROOT) && falhou=""; for t in $(TARGETS); do \
		printf '==> %s\n' "$$t"; \
		$(PY) targets/$$t/eval.py --budget || falhou="$$falhou $$t"; \
	done; \
	if [ -n "$$falhou" ]; then echo; echo "DIMENSIONAMENTO FORA DA FAIXA EM:$$falhou"; exit 1; fi

## verify: lint + test + selftest + budget. E o que o CI roda e o que um PR precisa passar
verify: lint test selftest budget
	@echo
	@echo "verify: tudo verde ($(words $(TARGETS)) alvos)."

## run: abre um run e imprime o primeiro prompt — make run TARGET=etl_agg [STEPS=n]
run:
	@cd $(ROOT) && $(PY) -m avo start --target $(TARGET) --max-steps $(STEPS)

## submit: fecha o passo do jeito certo — make submit RUN=runs/<id> M="resumo medido"
submit:
	@if [ -z "$(M)" ]; then \
		echo 'ERRO: falta M="o que mudou e quanto mediu".'; \
		echo 'Uso: make submit RUN=runs/<id> M="passe unico: 6877 -> 10275 (+49%)"'; \
		exit 2; \
	fi
	@cd $(ROOT) && $(PY) -m avo submit $(if $(RUN),--run $(RUN),) -m "$(M)"

## status: resumo do run — make status [RUN=runs/<id>]
status:
	@cd $(ROOT) && $(PY) -m avo status $(if $(RUN),--run $(RUN),)

## clean: remove caches de ferramenta e bytecode (nao toca em datasets nem runs)
clean:
	@cd $(ROOT) && rm -rf .pytest_cache .ruff_cache
	@cd $(ROOT) && find . -path ./vendor -prune -o -name '__pycache__' -type d -print0 \
		| xargs -0 --no-run-if-empty rm -rf
	@cd $(ROOT) && find . -path ./vendor -prune -o -name '*.pyc' -type f -delete
	@echo "caches removidos (datasets e runs preservados; use clean-data para os datasets)"

## clean-data: apaga os datasets gerados — 'make data' os reconstroi identicos
clean-data:
	@cd $(ROOT) && rm -rf targets/*/data
	@echo "datasets removidos. O dataset.lock.json ficou: 'make data' tem que reproduzir os mesmos SHA256."
