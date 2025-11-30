import os

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from granola.config import config


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # API Key
        self.api_key_edit = QLineEdit(config.get("api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Paste your Gemini API Key here")
        form.addRow("Gemini API Key:", self.api_key_edit)

        # Output Directory
        self.output_dir_edit = QLineEdit(config.get("output_dir", ""))
        self.output_dir_btn = QPushButton("Browse...")
        self.output_dir_btn.clicked.connect(self.browse_output_dir)
        form.addRow("Recordings Path:", self.output_dir_edit)
        form.addRow("", self.output_dir_btn)

        layout.addLayout(form)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Recordings Directory", self.output_dir_edit.text()
        )
        if path:
            self.output_dir_edit.setText(path)

    def save_settings(self):
        api_key = self.api_key_edit.text().strip()
        output_dir = self.output_dir_edit.text().strip()

        # Validation
        if not api_key:
            QMessageBox.warning(self, "Invalid Input", "API Key cannot be empty.")
            return

        if not output_dir:
            QMessageBox.warning(self, "Invalid Input", "Output directory cannot be empty.")
            return

        # Check if output directory exists or can be created
        try:
            os.makedirs(output_dir, exist_ok=True)
            # Check writability
            test_file = os.path.join(output_dir, ".write_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
        except Exception as e:
            QMessageBox.warning(self, "Invalid Input", f"Output directory is not writable:\n{e}")
            return

        config.set("api_key", api_key)
        config.set("output_dir", output_dir)
        self.accept()
