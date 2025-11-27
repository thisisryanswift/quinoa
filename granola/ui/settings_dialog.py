from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QFileDialog,
    QDialogButtonBox,
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
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
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
        config.set("api_key", self.api_key_edit.text())
        config.set("output_dir", self.output_dir_edit.text())
        self.accept()
