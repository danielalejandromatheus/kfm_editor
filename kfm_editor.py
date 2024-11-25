#!/usr/bin/env python

import sys
import os
import io

import traceback

from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QFileDialog, QTabWidget, QMenuBar, QMenu, QAction, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QHBoxLayout, QWidget, QPlainTextEdit, QLineEdit, QLabel, QMessageBox, QToolBar, QFormLayout, QSizePolicy, QOpenGLWidget, QHeaderView, QShortcut, QTreeWidgetItemIterator)
from PyQt5.QtGui import (QFont, QKeySequence)

from PyQt5.QtCore import Qt
from PyQt5 import QtCore


from dataclasses import dataclass
from typing import Any, Optional
from enum import Enum

from our_pyffi.pyffi.formats.kfm import KfmFormat

vertical_scroll_before_clear = None

class TextBoxWriter:
    def __init__(self, text_box):
        self.text_box = text_box

    def write(self, text):
        self.text_box.insertPlainText(text)
        if vertical_scroll_before_clear is not None:
            self.text_box.verticalScrollBar().setValue(vertical_scroll_before_clear) 
        sys.stderr.write(text)
    def flush(self):
        pass

class CommandType(Enum):
    EDIT_NIF_FILENAME = "edit_nif_filename"
    EDIT_NUM_ANIMATIONS = "edit_num_animations" 
    
    EDIT_ANIMATION_KF_FILENAME = "edit_animation_kf_filename"
    EDIT_ANIMATION_EVENT_CODE = "edit_animation_event_code"
    EDIT_ANIMATION_INDEX = "edit_animation_index"

    REMOVE_ANIMATION = "remove_animation"
    REMOVE_TRANSITION = "remove_transition"
    
    EDIT_NUM_TRANSITIONS = "edit_num_transitions"
    
    EDIT_TRANSITION_ANIMATION = "edit_transition_animation"
    EDIT_TRANSITION_TYPE = "edit_transition_type"

@dataclass
class Command:
    type: CommandType
    new_value: Any = None
    animation_index: Optional[int] = None
    transition_index: Optional[int] = None

    def __str__(self):
        return f"{self.type.value} : {self.new_value}"
    
class CommandManager:
    def __init__(self, uber, max_history=100):
        self.uber = uber

        self.history = []
        self.history_pointer = 0

        self.max_history = max_history
        self.command_handlers = {}

        def create_handler(func):
            def wrapper(*args):
                try:
                    func(*args)
                    return True
                except Exception:
                    print(traceback.format_exc())
                    return False
            return wrapper

        @create_handler
        def handle_nif_filename(new_value, *args):
            self.uber.data.nif_file_name = new_value

        @create_handler
        def handle_num_animations(new_value, *args):
            old_value = self.uber.data.num_animations
            new_value = int(new_value)

            self.uber.data.num_animations = new_value
            self.uber.data.animations.update_size()

            event_codes = set()
            for a in self.uber.data.animations:
                event_codes.add(a.event_code)

            next_anim = max(event_codes) + 1

            added_codes = set()

            if old_value < new_value:
                for i in range(old_value, new_value):
                    self.uber.data.animations[i].event_code = next_anim
                    
                    self.uber.data.animations[i].num_transitions = old_value
                    self.uber.data.animations[i].transitions.update_size()

                    it = 0
                    for j in range(old_value):
                        if i != j:
                            self.uber.data.animations[i].transitions[it].animation = self.uber.data.animations[j].event_code
                            self.uber.data.animations[i].transitions[it].type = 5
                        it += 1

                    added_codes.add(next_anim)
                    print(f"\n Next animation event code {next_anim}")
                    print("... adding transition to every other animation.\n")

                    next_anim += 1

            for at, a in enumerate(self.uber.data.animations):
                local = list(added_codes - set([a.event_code]))

                old_count = a.num_transitions
                a.num_transitions += len(local)
                a.transitions.update_size()

                for ii, i in enumerate(range(old_count, old_count + len(local))):
                    a.transitions[i].animation = local[ii]
                    a.transitions[i].type = 5
                    print(f"... adding transition to {local[ii]} for Animation {at + 1}")


        @create_handler
        def handle_animation(prop, new_value, anim_idx, *args):
            setattr(self.uber.data.animations[anim_idx], prop, new_value)

        @create_handler
        def handle_event_code(new_value, anim_idx, *args):
            anim = self.uber.data.animations[anim_idx]

            new_value = int(new_value)
            
            for ia, a in enumerate(self.uber.data.animations):
                if new_value == a.event_code:
                    print(f"Event code already used by Animation {ia + 1}")
                    return

            old_value = anim.event_code
            anim.event_code = int(new_value)

            for ia, a in enumerate(self.uber.data.animations):
                for it, t in enumerate(a.transitions):
                    if t.animation == old_value:
                        t.animation = new_value
                        print(f"... updating transition for Animation {ia + 1}, event code {old_value} -> {new_value}")
            
        @create_handler
        def handle_num_transitions(new_value, anim_idx, *args):
            self.uber.data.animations[anim_idx].num_transitions = int(new_value)
            self.uber.data.animations[anim_idx].transitions.update_size()

        @create_handler
        def handle_transition_property(prop, new_value, anim_idx, transition_index):
            if prop == 'animation':
                found = False
                for ia, a in enumerate(self.uber.data.animations):
                    if new_value == a.event_code:
                        found = True
                if not found:
                    print(f"Can't find animation with event code {new_value}")
                    return
            
            setattr(self.uber.data.animations[anim_idx].transitions[transition_index], prop, new_value)

        @create_handler
        def handle_remove_animation(_, anim_idx, *args):
            anim = self.uber.data.animations[anim_idx]
            event_code = anim.event_code

            for i in range(anim_idx, self.uber.data.num_animations-1):
                a1, a2 = self.uber.data.animations[i], self.uber.data.animations[i+1]
                a1.kf_file_name = a2.kf_file_name
                a1.event_code = a2.event_code
                a1.index = a2.index
                a1.num_transitions = a2.num_transitions
                a1.transitions.update_size()
                for j in range(a1.num_transitions):
                    a1.transitions[j].animation = a2.transitions[j].animation
                    a1.transitions[j].type = a2.transitions[j].type


            self.uber.data.num_animations -= 1
            self.uber.data.animations.update_size()

            for ia, a in enumerate(self.uber.data.animations):
                for it, t in enumerate(a.transitions):
                    if t.animation == event_code:
                        for i in range(it, len(a.transitions)-1):
                            t1, t2 = a.transitions[i], a.transitions[i+1]
                            t1.animation = t2.animation
                            t1.type = t2.type

                        a.num_transitions -= 1
                        a.transitions.update_size()

                        print(f"... removing transition for Animation {ia + 1}")

                        break

        @create_handler
        def handle_remove_transition(_, anim_idx, transition_index):
            anim = self.uber.data.animations[anim_idx]

            for i in range(transition_index, anim.num_transitions-1):
                t1, t2 = anim.transitions[i], anim.transitions[i+1]
                t1.animation = t2.animation
                t1.type = t2.type

            anim.num_transitions -= 1
            anim.transitions.update_size()

        self.command_handlers.update({
            CommandType.EDIT_NIF_FILENAME: handle_nif_filename,
            CommandType.EDIT_NUM_ANIMATIONS: handle_num_animations,
            CommandType.EDIT_ANIMATION_KF_FILENAME: lambda *args: handle_animation('kf_file_name', *args),
            CommandType.EDIT_ANIMATION_EVENT_CODE: handle_event_code,
            CommandType.EDIT_ANIMATION_INDEX: lambda new_value, *args: handle_animation('index', int(new_value), *args),
            CommandType.EDIT_NUM_TRANSITIONS: handle_num_transitions,
            CommandType.EDIT_TRANSITION_ANIMATION: lambda new_value, *args: handle_transition_property('animation', int(new_value), *args),
            CommandType.EDIT_TRANSITION_TYPE: lambda new_value, *args: handle_transition_property('type', int(new_value), *args),
            CommandType.REMOVE_ANIMATION: handle_remove_animation,
            CommandType.REMOVE_TRANSITION: handle_remove_transition,
        })

    def execute(self, command: Command) -> bool:
        if command.type not in self.command_handlers:
            return False
        
        handler = self.command_handlers[command.type]
        success = handler(command.new_value, command.animation_index, command.transition_index)

        if success:
            data = io.BytesIO()
            console_text = self.uber.console_text_box.toPlainText()
            self.uber.data.write(data)

            self.history = self.history[:self.history_pointer+1]
            self.history.append((command, data, console_text))

            self.history_pointer += 1

            if len(self.history) > self.max_history:
                self.history.pop(0)
                self.history_pointer -= 1
        else:
            data.seek(0)
            self.uber.data.read(data)


        self.uber.unsaved_changes = True

        self.uber.refresh_ui(command.animation_index if command.type == CommandType.REMOVE_ANIMATION else None, command.transition_index if command.type == CommandType.REMOVE_TRANSITION else None)

        print()

        return success
        
    def reread(self):
        try:
            self.uber.data = KfmFormat.Data()
            buf = self.history[self.history_pointer][1]
            buf.seek(0)
            self.uber.data.read(buf)

            txt = self.history[self.history_pointer][2]
            self.uber.console_text_box.setPlainText(txt)

            cursor = self.uber.console_text_box.textCursor()
            cursor.setPosition(len(txt))
            
            self.uber.console_text_box.setTextCursor(cursor)
        
            self.uber.unsaved_changes = True
        except Exception as e:
            print(traceback.format_exc())

        self.uber.refresh_ui()
        
    def undo(self):
        if self.history_pointer > 0:
            self.history_pointer -= 1
            self.reread()
        
    def redo(self):
        if self.history_pointer < len(self.history) - 1:
            self.history_pointer += 1
            self.reread()
        
class MyTreeWidget(QTreeWidget):
    def __init__(self, uber):
        super().__init__()
        self.uber = uber

    def keyPressEvent(self, event):
        selected_item = self.currentItem()
        
        if selected_item:
            if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
                if selected_item.childCount() == 0:
                    self.editItem(selected_item, 2)
                else:
                    if selected_item.isExpanded():
                        selected_item.setExpanded(False)
                    else:
                        selected_item.setExpanded(True)
            elif event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
                self.delete_item(selected_item)
            else:
                super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.pos())
        if item:
            column = self.columnAt(event.pos().x())
            if item.childCount() == 0:
                # Only allow editing on double-click if it's the third column
                if column == 2:
                    self.editItem(item, column)
            else:
                if item.isExpanded():
                    item.setExpanded(False)
                else:
                    item.setExpanded(True)
        else:
            # Call the base class method if no item is under the mouse
            super().mouseDoubleClickEvent(event)

    def delete_item(self, item):
        if item and item.parent() and item.text(0).startswith("Animation "): 
            self.uber.remove_animation(item)
        elif item and item.parent() and item.text(0).startswith("Transition "): 
            self.uber.remove_transition(item)

class UberKFM(QMainWindow):
    def __init__(self):
        super().__init__()

        self.unsaved_changes = False
        self.handle_item_connection = None

        self.setMinimumSize(1500, 700) 

        self.show()
        self.setWindowTitle('KFM Editor')
        self.setGeometry(300, 300, 800, 600)

        menuBar = QMenuBar(self)
        self.setMenuBar(menuBar)

        import platform
        if platform.system() == "Darwin":
            menuBar.setNativeMenuBar(False)

        missionMenu = QMenu("&File", self)
        menuBar.addMenu(missionMenu)

        action = QAction(self)
        action.setText("&Load (Ctrl + O)")
        action.triggered.connect(self.load_mission)
        missionMenu.addAction(action)

        action = QAction(self)
        action.setText("&Save (Ctrl + S)")
        action.triggered.connect(lambda: self.save_mission(ask=False))
        missionMenu.addAction(action)

        action = QAction(self)
        action.setText("&Save As ... (Ctrl + Shift + S)")
        action.triggered.connect(lambda: self.save_mission())
        missionMenu.addAction(action)

        editMenu = QMenu("&Edit", self)
        menuBar.addMenu(editMenu)

        action = QAction(self)
        action.setText("&Undo (Ctrl + Z)")
        action.triggered.connect(lambda: self.command_manager.undo())
        editMenu.addAction(action)

        action = QAction(self)
        action.setText("&Redo (Ctrl + Shift + Z)")
        action.triggered.connect(lambda: self.command_manager.redo())
        editMenu.addAction(action)

        self.console_text_box = QPlainTextEdit(self)
        self.console_text_box.setFont(QFont("Courier", 10))  
        self.console_text_box.setReadOnly(True)
        self.console_text_box.setLineWrapMode(QPlainTextEdit.WidgetWidth) 
        self.console_text_box.setFixedWidth(400)
        sys.stdout = TextBoxWriter(self.console_text_box)
                
        undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        undo_shortcut.activated.connect(lambda: self.command_manager.undo())
        
        redo_shortcut = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        redo_shortcut.activated.connect(lambda: self.command_manager.redo())

        open_shortcut = QShortcut(QKeySequence("Ctrl+O"), self)
        open_shortcut.activated.connect(self.load_mission)
        
        save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(lambda: self.save_mission(ask=False))

        save_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        save_shortcut.activated.connect(lambda: self.save_mission())

        self.command_manager = CommandManager(self)


    def handle_item_changed(self, item, column):
        try:
            new_value = item.text(2)
            command_type = None
            animation_index = None
            transition_index = None
            
            if item.text(0) == "NIF File Name":
                command_type = CommandType.EDIT_NIF_FILENAME
            elif item.text(0) == "Num Transitions":
                animation_index = int(item.parent().text(0).split()[1])-1
                command_type = CommandType.EDIT_NUM_TRANSITIONS
            elif item.text(0) == "Num Animations":
                command_type = CommandType.EDIT_NUM_ANIMATIONS
            elif item.text(0) == "KF File Name":
                animation_index = int(item.parent().text(0).split()[1])-1
                command_type = CommandType.EDIT_ANIMATION_KF_FILENAME
            elif item.text(0) == "Event Code":
                animation_index = int(item.parent().text(0).split()[1])-1
                command_type = CommandType.EDIT_ANIMATION_EVENT_CODE
            elif item.text(0) == "Index":
                animation_index = int(item.parent().text(0).split()[1])-1
                command_type = CommandType.EDIT_ANIMATION_INDEX
            elif item.text(0) == "Animation":
                animation_index = int(item.parent().parent().parent().text(0).split()[1])-1
                transition_index = int(item.parent().text(0).split()[1])-1
                command_type = CommandType.EDIT_TRANSITION_ANIMATION
            elif item.text(0) == "Type":
                animation_index = int(item.parent().parent().parent().text(0).split()[1])-1
                transition_index = int(item.parent().text(0).split()[1])-1
                command_type = CommandType.EDIT_TRANSITION_TYPE
            
            if command_type:
                self.command_manager.execute(Command(
                    type=command_type,
                    new_value=new_value,
                    animation_index=animation_index,
                    transition_index=transition_index
                ))
        except Exception as e:
            print(traceback.format_exc())

    def rebuild_tree(self):
        try:
            tree = self.tree
            data = self.data

            if self.handle_item_connection:
                tree.itemChanged.disconnect(self.handle_item_connection)

            tree.clear()

            def make_item_editable(item):
                item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)

            QTreeWidgetItem(self.tree, ["Header String", "HeaderString", KfmFormat.HeaderString.version_string(self.data.version)])
            make_item_editable(QTreeWidgetItem(self.tree, ["NIF File Name", "SizedString", data.nif_file_name.decode("ascii")]))
            make_item_editable(QTreeWidgetItem(self.tree, ["Num Animations", "int", str(len(data.animations))]))

            animations_item = QTreeWidgetItem(self.tree, ["Animations", "Animation[]", ""])
            for index in range(self.data.num_animations):
                anim = self.data.animations[index]
                anim_item = QTreeWidgetItem(animations_item, [f"Animation {index + 1}", "Animation", ""])
                make_item_editable(QTreeWidgetItem(anim_item, ["KF File Name", "SizedString", anim.kf_file_name.decode("ascii")]))
                make_item_editable(QTreeWidgetItem(anim_item, ["Event Code", "int", str(anim.event_code)]))
                make_item_editable(QTreeWidgetItem(anim_item, ["Index", "int", str(anim.index)]))
                make_item_editable(QTreeWidgetItem(anim_item, ["Num Transitions", "int", str(anim.num_transitions)]))
                transitions_item = QTreeWidgetItem(anim_item, ["Transitions", "Transitions[]", ""])

                for i in range(anim.num_transitions):
                    transition_i = QTreeWidgetItem(transitions_item, [f"Transition {i + 1}", "Transition", ""])
                    make_item_editable(QTreeWidgetItem(transition_i, ["Animation", "int", str(anim.transitions[i].animation)]))
                    make_item_editable(QTreeWidgetItem(transition_i, ["Type", "int", str(anim.transitions[i].type)]))

            self.handle_item_connection = tree.itemChanged.connect(self.handle_item_changed)
        except:
            print(traceback.format_exc())

    def refresh_ui(self, deleted_animation_index = None, deleted_transition_index = None):
        # Store the current scroll position
        scrollbar = self.tree.verticalScrollBar()
        scroll_pos = scrollbar.value()
        
        # Remember expanded items
        expanded_items = []
        current_item_path = None
        iterator = QTreeWidgetItemIterator(self.tree)

        while iterator.value():
            item = iterator.value()
            itemTemp = item

            path = []
            while itemTemp:
                path.insert(0, itemTemp.text(0))
                itemTemp = itemTemp.parent()

            if item.isExpanded():
                if deleted_animation_index is None or f"Animation {deleted_animation_index+1}" not in path:
                    if deleted_transition_index is None or f"Transition {deleted_transition_index+1}" not in path:
                        expanded_items.append(path)
            if item == self.tree.currentItem():
                current_item_path = path
            iterator += 1

        self.rebuild_tree()
        
        # Restore expanded state
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            current_path = []
            temp_item = item
            while temp_item:
                current_path.insert(0, temp_item.text(0))
                temp_item = temp_item.parent()
            if current_path in expanded_items:
                item.setExpanded(True)
            if current_item_path and current_path == current_item_path:
                self.tree.setCurrentItem(item)
            iterator += 1
            
        # Restore scroll position
        scrollbar.setValue(scroll_pos)

        self.tree.setFocus()

        star = " *" if self.unsaved_changes else ""
        self.setWindowTitle(f'KFM Editor {self.opened_filename} {star}')

    def remove_animation(self, item):
        parent_item = item.parent()
        index_to_remove = parent_item.indexOfChild(item)
        self.command_manager.execute(Command(
            type=CommandType.REMOVE_ANIMATION,
            animation_index=index_to_remove,
        ))
    
    def remove_transition(self, item):
        anim_id = item.parent().parent().parent().indexOfChild(item.parent().parent())

        parent_item = item.parent()
        index_to_remove = parent_item.indexOfChild(item)

        self.command_manager.execute(Command(
            type=CommandType.REMOVE_TRANSITION,
            animation_index=anim_id,
            transition_index=index_to_remove,
        ))

    def init_ui(self):
        self.setCentralWidget(None)

        main_layout = QHBoxLayout()

        self.tree = MyTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Type", "Value"])
        self.tree.setAlternatingRowColors(True)

        def show_context_menu(position):
            item = self.tree.itemAt(position)
            if item and item.parent() and item.text(0).startswith("Animation "): 
                menu = QMenu(self.tree)
                
                remove_action = QAction("Remove", self.tree)
                remove_action.triggered.connect(lambda: self.remove_animation(item))
                menu.addAction(remove_action)
                
                menu.exec_(self.tree.viewport().mapToGlobal(position))
            elif item and item.parent() and item.text(0).startswith("Transition "): 
                menu = QMenu(self.tree)
                
                remove_action = QAction("Remove", self.tree)
                remove_action.triggered.connect(lambda: self.remove_transition(item))
                menu.addAction(remove_action)
                
                menu.exec_(self.tree.viewport().mapToGlobal(position))

        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(show_context_menu)

        header = self.tree.header()       
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        main_layout.addWidget(self.tree)

        self.rebuild_tree()

        self.refresh_ui()

        output_and_recalc_button = QVBoxLayout()
        output_and_recalc_button.addWidget(self.console_text_box)

        main_layout.addLayout(output_and_recalc_button)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def prompt_unsaved_should_continue(self):
        accept = False
        if self.unsaved_changes:
            reply = QMessageBox.question(self, 'Unsaved Changes',
                                         "You have unsaved changes. Do you want to save before exiting?",
                                         QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)
            if reply == QMessageBox.Yes:
                if self.save_mission():
                    accept = True
            elif reply == QMessageBox.No:
                accept = True
        else:
            accept = True
        return accept

    def load_mission_file(self, filename):
        print("Reading", filename, "...")
        try:
            with open(filename, 'rb') as file:
                self.opened_filename = filename
                self.filename_dir = os.path.dirname(filename)

                self.data = KfmFormat.Data()
                self.data.inspect(file)
                self.data.read(file)
            
                print("... version", self.data.version)

                print("    NIF File Name", self.data.nif_file_name.decode("ascii"))
                print("    Found", len(self.data.animations), "animations\n")

                self.init_ui()

                data = io.BytesIO()
                console_text = self.console_text_box.toPlainText()
                self.data.write(data)
                self.command_manager.history = [(None, data, console_text)]

                self.unsaved_changes = False
        except:
            print(traceback.format_exc())

    def load_mission(self):
        if self.prompt_unsaved_should_continue():
            options = QFileDialog.Options()
            filename, _ = QFileDialog.getOpenFileName(self, "Load KFM File", "", "KFM Files (*.kfm);;All Files (*)", options=options)
            if filename:
                self.load_mission_file(filename)

    def get_default_save_filename(base_filename):
        base_name, ext = os.path.splitext(base_filename)
        new_filename = base_filename
        count = 1
        while os.path.exists(new_filename):
            new_filename = f"{base_name}_{count}{ext}"
            count += 1
        return new_filename

    def save_mission(self, ask=True):
        if getattr(self, "data", None) is not None:
            if ask:
                options = QFileDialog.Options()
                filename, _ = QFileDialog.getSaveFileName(self, "Save KFM File", UberKFM.get_default_save_filename(self.opened_filename), "KFM Files (*.kfm);;All Files (*)", options=options)
            else:
                filename = self.opened_filename
            if filename:
                with open(filename, 'wb') as file:
                    if self.data:
                        self.data.write(file)
                        self.unsaved_changes = False
                        self.refresh_ui()
                return True
            else:
                return False

    def closeEvent(self, event):
        if self.prompt_unsaved_should_continue():
            event.accept()
        else:
            event.ignore()

if __name__ == '__main__':
    app = QApplication(sys.argv)

    window = UberKFM()
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        window.load_mission_file(file_path)  

    sys.exit(app.exec_())
