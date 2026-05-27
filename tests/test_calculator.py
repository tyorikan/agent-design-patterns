"""Calculatorクラスのテストモジュール。"""

import pytest
from shared.calculator import Calculator


@pytest.fixture
def calculator() -> Calculator:
    """テスト用のCalculatorインスタンスを提供するフィクスチャ。"""
    return Calculator()


def test_add(calculator: Calculator) -> None:
    """加算メソッドのテスト。"""
    assert calculator.add(1, 2) == 3
    assert calculator.add(-1, 1) == 0
    assert calculator.add(1.5, 2.5) == 4.0


def test_subtract(calculator: Calculator) -> None:
    """減算メソッドのテスト。"""
    assert calculator.subtract(5, 2) == 3
    assert calculator.subtract(2, 5) == -3
    assert calculator.subtract(5.5, 1.5) == 4.0


def test_multiply(calculator: Calculator) -> None:
    """乗算メソッドのテスト。"""
    assert calculator.multiply(3, 4) == 12
    assert calculator.multiply(-2, 3) == -6
    assert calculator.multiply(2.5, 2) == 5.0


def test_divide(calculator: Calculator) -> None:
    """除算メソッドのテスト。"""
    assert calculator.divide(6, 3) == 2.0
    assert calculator.divide(5, 2) == 2.5
    assert calculator.divide(-6, 3) == -2.0


def test_divide_by_zero(calculator: Calculator) -> None:
    """ゼロ除算エラーに対するテスト。"""
    with pytest.raises(ValueError, match="0で割ることはできません。"):
        calculator.divide(5, 0)
