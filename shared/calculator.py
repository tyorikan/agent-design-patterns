"""計算機モジュール。"""


class Calculator:
    """基本的な算術演算（加算、減算、乗算、除算）を行う計算機クラスです。"""

    def add(self, a: float | int, b: float | int) -> float | int:
        """2つの数値を加算します。"""
        return a + b

    def subtract(self, a: float | int, b: float | int) -> float | int:
        """2つの数値を減算します。"""
        return a - b

    def multiply(self, a: float | int, b: float | int) -> float | int:
        """2つの数値を乗算します。"""
        return a * b

    def divide(self, a: float | int, b: float | int) -> float:
        """aをbで除算します。

        Raises:
            ValueError: 0で除算しようとした場合。
        """
        if b == 0:
            raise ValueError("0で割ることはできません。")
        return a / b
