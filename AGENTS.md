# AGENTS.md — llp-spec

Norma del wire **LLP v4** y del perfil **R1**, más el corpus de conformidad y la
implementación de referencia en Python. Este repo es la **fuente de verdad** del
protocolo: `llp-protocol`, `llp-protocol-java` y los firmwares lo implementan;
ninguno define el wire por su cuenta.

**Este archivo es normativo**: solo invariantes y comandos. El formato, los
canales y la semántica viven en `README.md` y `docs/`.

## Orden de cambio

1. `llp-spec` — spec y vectores.
2. `llp-protocol` / `llp-protocol-java` — implementaciones.
3. Firmwares y aplicación.

Un cambio **incompatible con el wire** exige bump de **major** acá y en cada repo
que lo implemente; se documenta con un ADR en `llp-protocol/docs/DECISIONS.md`.
No hay modo dual entre generaciones de wire.

## Comandos

```bash
python3 tools/build_vectors.py --check && python3 tools/validate_vectors.py
python3 tools/selftest_reliability.py
```

Checks auxiliares:

```bash
python3 tools/check_schema.py              # JSON Schema sobre vectors/
python3 tools/check_vendor.py              # pin de la referencia vendorizada
python3 tools/selftest_reference.py        # referencia vs ejemplos de la spec
python3 tools/generate_fuzz_seeds.py --check
```

Regenerar (solo tras agregar casos al generador):

```bash
python3 tools/build_vectors.py                   # vectors/ + MANIFEST.sha256
python3 tools/build_vectors.py --update-readme   # tabla del README
python3 tools/build_vectors.py --emit-c <ruta>   # fixture C para consumidores
```

El total de vectores y su desglose los imprime `validate_vectors.py`; no los
cites de memoria.

## Invariantes

- **Los vectores son el contrato** entre implementaciones. No se editan a mano:
  se agrega el caso a la función `build_*_vectors()` del generador y se
  regenera. El generador rechaza un caso que la referencia no reproduce, así que
  un self-check fallido significa que la expectativa está mal (o cambió la spec).
- **`vectors/MANIFEST.sha256` pinea el corpus.** Todo consumidor que lo
  vendoriza (fixture C, recursos de test de Java) verifica ese manifiesto; si
  cambian los vectores, hay que re-sincronizar sus copias en el mismo hito.
- **`reference/llp_v4.py` es vendorizado**: origen y sha256 están en
  `reference/VENDOR.md`. No se edita a mano; se actualiza desde el repo de
  origen y se re-pinea.
- **La tabla de vectores del `README.md` es generada** (`--update-readme`). No
  editarla a mano.
- **El schema versiona aparte del wire** (`schema/vector.schema.json`): un
  cambio de schema no cambia el wire, y viceversa.
- **La referencia Python es literal y sin dependencias**: se translitera a otros
  lenguajes. No la optimices a costa de legibilidad.
- **Sin datos volátiles** en docs (conteos, versiones, tamaños): da el comando
  que los obtiene.

## Documentación

| archivo | contenido |
|---|---|
| `README.md` | vista general, formato, canales, estructura y checks |
| `docs/SPEC-v4.md` | norma del wire: estados, errores, timeouts, invariantes |
| `docs/RELIABILITY.md` | norma del perfil R1: canales 1/2/3, dedup, HELLO |
| `docs/CONFORMANCE.md` | schema de vectores, reglas por `kind` y checklist |

Un cambio de wire actualiza la spec **y** los vectores en el mismo cambio; el
`README.md` lo resume, no lo define.

## Git

- `dev` y `main` son **ramas protegidas**: solo PR, nunca commits directos.
- Ramas `feature/<scope>-<slug>`, `fix/<slug>`, `docs/<slug>`, `hotfix/<slug>`.
- Un PR = un tema; squash a `dev`; release `dev → main` con tag anotado.
- Commits Conventional Commits **en español**; la spec y los vectores en inglés.
