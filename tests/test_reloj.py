# Tests de src/reloj.py: cuánto puede pensar MiniMate con reloj.
# Se corren con: pytest

from src.reloj import (CONTROLES, TIEMPO_ESTIMADO, profundidad_segun_reloj,
                       tiempo_para_esta_jugada)


def test_controles():
    assert CONTROLES["Sin reloj"] is None
    assert CONTROLES["5+3"] == (300, 3)
    assert list(CONTROLES) == ["Sin reloj", "3+2", "5+3", "10+5", "15+10"]


def test_presupuesto_por_jugada():
    # 5 minutos, +3: 300/30 + 3*0.8 = 12.4 segundos.
    assert abs(tiempo_para_esta_jugada(300, 3) - 12.4) < 1e-9
    # Nunca más de la mitad de lo que queda.
    assert tiempo_para_esta_jugada(2, 10) == 1


def test_con_tiempo_de_sobra_usa_la_profundidad_del_nivel():
    assert profundidad_segun_reloj(3, True, 600, 5) == 3
    assert profundidad_segun_reloj(2, True, 180, 2) == 2


def test_con_poco_tiempo_baja_la_profundidad():
    # 3+2 con 20 segundos: presupuesto 20/30 + 1.6 = 2.27 s, menos de lo que
    # puede tardar la profundidad 3 (3 s): baja a 2.
    assert TIEMPO_ESTIMADO[(3, True)] > tiempo_para_esta_jugada(20, 2)
    assert profundidad_segun_reloj(3, True, 20, 2) == 2
    # Casi sin tiempo y sin incremento: lo mínimo, profundidad 1.
    assert profundidad_segun_reloj(3, True, 0.5, 0) == 1


def test_nunca_baja_de_uno_ni_sube():
    assert profundidad_segun_reloj(1, False, 0.01, 0) == 1
    assert profundidad_segun_reloj(2, False, 10000, 60) == 2
