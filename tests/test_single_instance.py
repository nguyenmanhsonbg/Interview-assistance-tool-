import tempfile
import unittest
from pathlib import Path


class SingleInstanceTests(unittest.TestCase):
    def test_second_lock_for_same_data_directory_is_rejected(self):
        from app.infrastructure.single_instance import SingleInstanceError, SingleInstanceLock

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "app.lock"
            first = SingleInstanceLock(path)
            second = SingleInstanceLock(path)
            first.acquire()
            try:
                with self.assertRaises(SingleInstanceError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
