import os
import shutil

import pyzipper
import json
import util
from util import logger
from qtpy import QtWidgets, QtGui, QtCore

PATH_FILES = "files"
PATH_LAST_FILE = os.path.join(PATH_FILES, "last.txt")

class PasswordRefusedException(RuntimeError):
    pass

class LibraryManager:
    def __init__(self):
        self.names = []
        self._cur_library = None

        # init files directory
        if not os.path.isdir(PATH_FILES):
            os.makedirs(PATH_FILES)

            # if did not exist, make default library
            self.new_library("Default")
            logger.debug("Init files directory and default library")
        else:
            # files directory did exist, so read existing libraries from the folder
            for file in os.listdir(PATH_FILES):
                name, ext = os.path.splitext(file)
                if ext == ".zip":
                    self.names.append(name)

        logger.info("{} libraries detected".format(len(self.names)))

    def new_library(self, name, pwd=None) -> "Library":
        if name in self.names:
            raise KeyError
        else:
            with Library(name, pwd) as library:
                library.save()
            self.names.append(name)
            return self.get_library(name, pwd)

    def get_library(self, name, pwd=None) -> "Library":
        try:
            if name not in self.names:
                raise KeyError
            else:
                if self._cur_library is not None:
                    if self._cur_library.name == name:
                        return self._cur_library
                    else:
                        self._cur_library.close()  # dispose of old library if any

                self._cur_library = Library(name, pwd)

                # write last library to filesystem
                with open(PATH_LAST_FILE, "w") as f:
                    f.write(name)
                return self._cur_library
        except PasswordRefusedException:
            util.warn("Password refused while trying to get library \"{}\" so "
                      "switching to default library instead".format(name))
            return self.get_default_library()

    def get_last_library(self) -> "Library":
        if os.path.isfile(PATH_LAST_FILE):
            with open(PATH_LAST_FILE, "r") as f:
                return self.get_library(f.read())
        else:
            return self.get_default_library()

    def get_default_library(self) -> "Library":
        return self.get_library("Default")  # in exceptional cases, error will be raised (such as when no libraries exist)

    def close(self):
        if self._cur_library is not None:
            self._cur_library.close()

    def __del__(self):
        self.close()

class Library:
    def __init__(self, name, pwd=None):
        self.name = name
        self._pwd = pwd

        self.path = os.path.join(PATH_FILES, self.name + ".zip")
        self.path_tmp = os.path.join(PATH_FILES, self.name + ".tmp.zip")
        self._closed = False

        # default config
        self.config = {
            "headers": [True, True, True, False, False, False, True, False],
        }
        self.meta = {}

        if os.path.isfile(self.path):
            self.prompt_password()

        self._fh = self.__open_fh()  # file handle. NB: remember to dispose correctly
        self._load()

    def __open_fh(self, path=None):
        if path is None:
            path = self.path

        fh = pyzipper.AESZipFile(path, "a", compression=pyzipper.ZIP_DEFLATED)
        self._apply_password(fh, self._pwd)

        return fh

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        self.close()

    def _apply_password(self, fh, pwd):
        if pwd is not None:
            fh.setencryption(pyzipper.WZ_AES)
            fh.setpassword(str(pwd).encode("utf8"))

    def save(self, recreate_fh=True):
        """
        :param recreate_fh: Zipfiles must be closed during the saving process. Set to True to recreate (reopen) the file handle after saving
        """
        try:
            if self._fh is not None:
                self._fh.close()
        except AttributeError:
            # happens when password refused and disposing Library object
            return

        # create new tmp archive
        with self.__open_fh(self.path_tmp) as fh_tmp:
            fh_tmp.writestr("config.json", json.dumps(self.config))
            fh_tmp.writestr("meta.json", json.dumps(self.meta))

        # replace old archive with new tmp archive
        shutil.move(self.path_tmp, self.path)

        # recreate fh
        if recreate_fh:
            self._fh = self.__open_fh()

        logger.debug("Library \"{}\" saved".format(self.name))

    def test_password(self, pwd):
        fh = self.__open_fh(self.path)
        try:
            self._apply_password(fh, pwd)

            with fh.open("config.json", "r") as f:
                return True
        except RuntimeError as e:
            if any([x in str(e) for x in ("requires a password", "Bad password")]):
                return False
            else:
                # other kind of error so re-raise
                raise
        finally:
            fh.close()

    def prompt_password(self):
        attempt_no = 0
        while True:
            if self.test_password(self._pwd):
                logger.debug("Password test for library \"{}\" succeeded".format(self.name))
                return
            else:
                msg = "The provided password was incorrect. Please try again: "
                if attempt_no <= 0:
                    logger.debug("Password required for library \"{}\". Prompting user.".format(self.name))
                    msg = "Library \"{}\" is encrypted. Please input password: ".format(self.name)

                # noinspection PyArgumentList
                text, ok = QtWidgets.QInputDialog.getText(None, "Password", msg, QtWidgets.QLineEdit.Password)
                if ok:
                    self._pwd = text
                else:
                    raise PasswordRefusedException("Password input: not ok")
            attempt_no += 1

    def _load(self):
        if "config.json" in self._fh.namelist():
            with self._fh.open("config.json", "r") as f:
                self.config = json.load(f)

        if "meta.json" in self._fh.namelist():
            with self._fh.open("meta.json", "r") as f:
                self.meta = json.load(f)

    def close(self):
        """
        NB: saves as well automatically
        """
        if not self._closed:
            self.save(False)  # recreate_fh=False => zipfile will be closed
            logger.debug("Library \"{}\" closed".format(self.name))
            self._closed = True

if __name__ == '__main__':
    # # for during dev only
    # manager = LibraryManager()
    # manager.new_library("test", "test")
    # del manager  # see notes issue #2
    pass
