import random
import unittest

from snake import Game, UP, DOWN, LEFT, RIGHT


class GameTests(unittest.TestCase):
    def make(self):
        g = Game(height=10, width=12, rng=random.Random(1))
        g.food = (1, 1)  # out of the way unless a test moves it
        return g

    def test_moves_right(self):
        g = self.make()
        head = g.snake[0]
        g.step()
        self.assertEqual(g.snake[0], (head[0], head[1] + 1))
        self.assertEqual(len(g.snake), 3)

    def test_cannot_reverse(self):
        g = self.make()
        g.turn(LEFT)
        g.step()
        self.assertEqual(g.direction, RIGHT)

    def test_double_turn_in_one_tick_cannot_reverse(self):
        g = self.make()
        g.turn(UP)
        g.turn(LEFT)  # LEFT is opposite of the travelled direction RIGHT
        g.step()
        self.assertEqual(g.direction, UP)
        self.assertFalse(g.over)

    def test_eating_grows_and_scores(self):
        g = self.make()
        h = g.snake[0]
        g.food = (h[0], h[1] + 1)
        g.step()
        self.assertEqual(g.score, 1)
        self.assertEqual(len(g.snake), 4)
        self.assertNotIn(g.food, g.snake)

    def test_wall_ends_game(self):
        g = self.make()
        for _ in range(20):
            g.step()
        self.assertTrue(g.over)
        self.assertFalse(g.won)

    def test_self_collision(self):
        g = self.make()
        g.snake = [(5, 5), (5, 6), (6, 6), (6, 5), (6, 4)]
        g.direction = g.pending = UP
        g.turn(RIGHT)
        g.step()  # head moves to (5, 6) which is body
        self.assertTrue(g.over)

    def test_following_tail_is_safe(self):
        g = self.make()
        g.snake = [(5, 5), (5, 6), (6, 6), (6, 5)]  # head moving down hits tail cell
        g.direction = g.pending = LEFT
        g.turn(DOWN)
        g.step()
        self.assertFalse(g.over)

    def test_filling_board_wins(self):
        g = Game(height=4, width=5, rng=random.Random(1))  # interior 2x3
        g.snake = [(1, 2), (1, 3), (2, 3), (2, 2), (2, 1)]
        g.food = (1, 1)
        g.direction = g.pending = LEFT
        g.step()
        self.assertTrue(g.won and g.over)


if __name__ == "__main__":
    unittest.main()
