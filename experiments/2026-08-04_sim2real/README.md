# Diagnóstico real-vs-sim — el cuello del sim2real es el enlace, no la física

Primera ejecución de `diagnose_real_vs_sim.py`, el "Paso 1 de mayor leverage" que el
plan del 2026-06-26 identificó y que **nunca se había corrido**. Seis semanas después, y
después de una campaña entera barriendo fricción, resulta que el diagnóstico apuntaba al
lugar correcto.

Modelo evaluado: `r7_ft_fr100_s0_best.zip` (el mejor candidato confirmado de junio, con
re-evaluación a 100 episodios). Sim con el `Dp` ya corregido a 7,52e-6.

## Resultado

| | reach% | min_dist | hold | acción media \|a\| | pasos saturados | pasos con \|θ\|>80° |
|---|---|---|---|---|---|---|
| **real** | **0%** | 68–89° | 0,00 s | **0,936** | **93,6%** | **91,3%** |
| sim | 100% | 0° | **9,43 s** | 0,111 | 1,5% | 0,0% |

La misma política, en el hierro, actúa con acciones **8 veces más grandes** y vive el 91%
del tiempo aplastada contra la abrazadera del modo 6. En la sim nunca pasa de 73° y usa
acciones suaves.

Una política determinista con la misma observación da la misma acción. Como las acciones
difieren tanto, **lo que difiere es la observación**.

## La causa: 14,3 Hz contra los 50 Hz de diseño

Medido directamente, un paso del lazo RL por HTTP tarda **69,9 ms**, porque son **dos**
viajes de ida y vuelta: `rl_cmd` para mandar la acción y `rl_state` para leer el estado.

```
paso real (rl_cmd + rl_state) = 69,9 ms  ->  14,3 Hz
periodo exigido por control_freq=50      = 20,0 ms
```

La política fue entrenada a 50 Hz. En el hierro corre **3,5× más lento**, así que cada
acción se sostiene 3,5 veces más de lo que ella espera. De ahí sale todo lo demás:

1. El brazo se pasa de largo y alcanza la abrazadera de 80°.
2. Ahí la observación queda **fuera de la distribución de entrenamiento** (en sim el
   brazo nunca superó 73°).
3. La política satura, lo que la clava más contra el tope. Es un lazo que se realimenta.

Le pone número a algo que ya estaba anotado como sospecha ("WiFi RT ~35 ms contra un
período de 20 ms"): son 70 ms por paso completo, no 35.

## Consecuencia: el modo 6 no es un banco de pruebas válido

Cualquier evaluación de una política de 50 Hz por HTTP **mide el enlace, no la política**.
Eso incluye muy probablemente el *"el deploy real del modelo de 95% dio hold ~0"* de
junio, que fue uno de los dos pilares que justificaron toda la investigación de fricción.
No se puede afirmar sin los datos de aquella corrida, pero el mecanismo estaba disponible
y el script era el mismo.

**Lo que NO se puede concluir de acá:** que la política sea buena. No se probó. Sólo se
probó que el modo 6 no puede probarla.

## Dos defectos encontrados en el camino (y por qué casi arruinan el diagnóstico)

### 1. La factory no exponía el homing — arrancar contra el tope

`make_real_env()` no tenía `homing_every` ni `homing_on_start` en su firma, así que
**por la factory el homing era inalcanzable** y todo evaluador construido con ella
arrancaba los episodios con el brazo donde hubiera quedado la corrida anterior.

En la primera corrida de hoy eso dio tres episodios empezando en **91–94°**: pasada la
abrazadera de 80° y a **un grado** del corte duro de 95°.

### 2. `/rl_state` se congela en silencio, y eso disfraza el fallo de catástrofe

Cuando el brazo cruzó los 95°, el firmware hizo `setMode(0)`. Como
`updateRlObservation()` **sólo corre en los modos 6 y 7**, `/rl_state` dejó de
actualizarse y siguió devolviendo el último valor. No falla, no avisa: **repite**.

La política corrió los 500 pasos restantes contra una observación muerta, saturando. El
resultado fue `reach=0%` con `min_dist=176°` —el péndulo "sin moverse"— que parecía una
brecha sim2real catastrófica y **no medía nada**.

La firma que lo delató: `theta` **exactamente constante** en las 1500 muestras
(`min = max = inicio = fin`), y `alpha` también. Un brazo físicamente trabado igual
mostraría ruido de encoder, y sobre todo **el péndulo cuelga libre: no puede estar
perfectamente inmóvil** mientras el motor empuja al 95%. Un estado que no cambia ni un
conteo no es un estado medido.

Con el homing activado, `min_dist` pasó de 176° a **68–89°**: el péndulo sí sube.

## Correcciones aplicadas

- `make_real_env()` acepta `homing_every` y `homing_on_start` y los pasa a `QubeRealEnv`.
- `diagnose_real_vs_sim.py` gana `--homing-every`, **con default 1** (homing en cada
  episodio). El default anterior de facto era "nunca".

## Cómo seguir

**El modo 7 corre la inferencia en la propia ESP32**, a la frecuencia del lazo y sin HTTP
en el medio. Ése es el único despliegue que puede evaluar honestamente una política de
50 Hz. Requiere exportar a `policy_weights.h` (`export_rltools`), verificar y flashear.

Complementario y barato: que **`rl_cmd` devuelva el estado en la misma respuesta**, para
pasar de dos viajes a uno (~35 ms). No llega a 50 Hz, pero deja de ser el factor
dominante si alguna vez se entrena sobre el hardware.

## Nota sobre el modelo entrenado hoy

`models/qube_sac_64x2.zip` (300k pasos desde cero con el `Dp` medido) **no aprendió la
tarea**: en sim da `reach=0%` y episodios de ~13 pasos. No es evidencia sobre el `Dp` —
es un entrenamiento desde cero mal dimensionado, contra unos `r7_ft_*` de junio que son
*fine-tuned* sobre un currículum previo. Al guardarse pisó el `qube_sac_64x2.zip` viejo,
que no estaba versionado; sobreviven todos los `r7_*` y los `qube_overnight_*`.
