import pytesseract, mss, requests, re, os, time, threading, sys, pyautogui, cv2
import numpy as np
from PIL import Image
from bs4 import BeautifulSoup
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from difflib import SequenceMatcher 

workingDir = os.path.dirname(os.path.abspath(__file__))

pytesseract.pytesseract.tesseract_cmd = workingDir + "/tesseract" + "/tesseract.exe"

if getattr(sys, 'frozen', False): 
    os.environ['TESSDATA_PREFIX'] = workingDir + "/tesseract"

questions_answers = {}

last_question = []

attempts = 0

# Словарь для замены похожих символов
REPLACEMENT_DICT = {
    'a': 'а', 'A': 'А', 'e': 'е', 'E': 'Е', 'o': 'о', 'O': 'О', 'p': 'р', 'P': 'Р',
    'c': 'с', 'C': 'С', 'y': 'у', 'Y': 'У', 'x': 'х', 'X': 'Х', 'b': 'б', 'B': 'Б',
    'H': 'Н', 'K': 'К', 'M': 'М', 'T': 'Т', '3': 'З', 'I': 'И', '}': ')'
}

def keep_black_only(image):
    # grayscale_image = image.convert("L")
    # binary_image = grayscale_image.point(lambda x: 0 if x < 150 else 255, '1')
    # return binary_image.convert("RGB")
    image_np = np.array(image)
    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY)
    return binary

def replace_with_russian(text):
    for eng_char, rus_char in REPLACEMENT_DICT.items():
        text = text.replace(eng_char, rus_char)
    return text

def jaccard_index(str1, str2):
    set1, set2 = set(str1.split()), set(str2.split())
    intersection = set1.intersection(set2)
    union = set1.union(set2)
    return len(intersection) / len(union) if union else 0

def similarity(str1, str2):
    return SequenceMatcher(None, str1, str2).ratio()

class OCRThread(QThread):
    show_warning_signal = pyqtSignal(str)

    def run(self):
        global attempts, finded, blocks, black_image
        with mss.mss() as sct:
            # Скриншот всего экрана
            screenshot = sct.grab(sct.monitors[1])
            image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

        black_image = keep_black_only(image)
        black_image = Image.fromarray(black_image)

        image.save("screenshot.png")
        black_image.save("bw_screenshot.png")

        raw_text = pytesseract.image_to_data(image, config=r'--oem 3 --psm 4', lang='rus', output_type=pytesseract.Output.DICT)

        blocks = []
        current_block = []

        for i, level in enumerate(raw_text['level']):
            if level == 3: 
                if current_block:  
                    blocks.append(" ".join(current_block).strip())
                    current_block = []
            elif level == 5:  
                word = raw_text['text'][i]
                if word.strip():  
                    current_block.append(word)

        if current_block: 
            blocks.append(" ".join(current_block).strip())

        finded = False

        for block_text in blocks:
            single_line_text = replace_with_russian(block_text.replace('\n', ' ').replace('}', ')').rstrip())
            if not(finded):
                find_answer(single_line_text)
            else: 
                return

        attempts += 1
        if attempts >= 10:
            stop_ocr()
            self.show_warning_signal.emit("Не видно вопроса. Остановка распознавания.")

def find_answer(query):
    global attempts, finded, window, last_question
    best_match, best_score, matched_coordinates = None, 0, []

    raw_text = pytesseract.image_to_data(black_image, config=r'--oem 3 --psm 4 --dpi 185', lang='rus', output_type=pytesseract.Output.DICT)

    blocks = []
    current_block = []

    for i, level in enumerate(raw_text['level']):
        if level == 3: 
            if current_block:  
                blocks.append(" ".join(current_block).strip())
                current_block = []
        elif level == 5:  
            word = raw_text['text'][i]
            if word.strip():  
                current_block.append(word)

    if current_block: 
        blocks.append(" ".join(current_block).strip())

    for question_text in questions_answers.keys():
        score = jaccard_index(query.lower(), question_text.lower())
        if score > best_score:
            best_score = score
            best_match = question_text

    if best_score > 0.5 and best_match:
        answer_text = ""
        for i, answer_group in enumerate(questions_answers[best_match]):
            if i > 0: 
                answer_text += "\nили\n"
            answer_text += "\n".join(answer_group)

        for answer in answer_group:
            answer = answer[3:]
            blocks.append(" ".join("Следующий вопрос").strip())

            # Добавляем поиск лучшего совпадения
            best_score = 0
            best_match = None

            for block_text in blocks:
                block_text = block_text[2:]
                score = jaccard_index(block_text, replace_with_russian(answer))
                if score > best_score:
                    best_score = score
                    best_match = block_text

            # Если есть хорошее совпадение (порог >= 0.93)
            if best_score >= 0.90 and best_match:
                word = best_match.split()
                word = word[0]
                for j, word_raw in enumerate(raw_text['text']):
                    if word_raw == word:
                        left = raw_text['left'][j]
                        top = raw_text['top'][j]
                        width = raw_text['width'][j]
                        height = raw_text['height'][j]
                        center_x = left + width // 2
                        center_y = top + height // 2
                        matched_coordinates.append((center_x, center_y))

        question_label.setText(f"Вопрос: {best_match}")
        answer_label.setText(f"Ответы:\n{answer_text}")
        
        if last_question != best_match:
            for coord in matched_coordinates:
                pyautogui.moveTo(coord[0], coord[1])
                pyautogui.click()
                time.sleep(1)

        last_question = best_match

        finded = True
        attempts = 0
    else:
        question_label.setText("Вопрос не найден")
        answer_label.setText("")

def start_ocr():
    global attempts, start
    attempts = 0 
    start = True
    status_label.setText("Статус: Запущен") 
    status_label.setStyleSheet("color: green;") 
    while start:
        ocr_thread.run()
        time.sleep(1)

def stop_ocr():
    global start
    status_label.setText("Статус: Остановлено")
    status_label.setStyleSheet("color: red;")
    question_label.setText("")
    answer_label.setText("")
    start = False

def load_website_data(url):
    global questions_answers

    questions_answers = {}

    try:
        response = requests.get(url)
        html_content = response.text
        soup = BeautifulSoup(html_content, "html.parser")

        questions = soup.find_all("h3")
        for question_tag in questions:
            question_text = re.sub(r'^\d+\.\s*', '', question_tag.text.strip())
            question_text = replace_with_russian(question_text.replace('\xad', '').replace('_', '').replace('  ', ' '))

            answers = []
            answer_tag = question_tag.find_next_sibling("p")
            if answer_tag:
                for answer in answer_tag.find_all("strong"):
                    answer_text = answer.text.strip()
                    answer_text = answer_text[:-2]
                    answers.append(answer_text)

            if question_text in questions_answers:
                questions_answers[question_text].append(answers)
            else:
                questions_answers[question_text] = [answers] 

        if questions_answers:
            ocr_button.setEnabled(True)
            stop_ocr_button.setEnabled(True)
        
        QMessageBox.information(window, "Загрузка завершена", "Данные с сайта успешно загружены!")
    except Exception as e:
        QMessageBox.critical(window, "Ошибка", f"Не удалось загрузить данные: {e}")

def main():
    app = QApplication([])
    global window
    window = QWidget()
    app.setWindowIcon(QIcon(f"{workingDir}/icon.ico"))
    window.setWindowTitle("Система поиска ответов")
    window.setGeometry(0, 0, 600, 300)

    window.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)

    layout = QVBoxLayout()

    url_label = QLabel("Введите URL сайта с ответами (24forcare.com):")
    layout.addWidget(url_label)
    url_entry = QLineEdit()
    layout.addWidget(url_entry)

    load_button = QPushButton("Загрузить данные")
    load_button.clicked.connect(lambda: load_website_data(url_entry.text()))
    layout.addWidget(load_button)

    global ocr_button, stop_ocr_button
    ocr_button = QPushButton("Запустить OCR")
    ocr_button.setEnabled(False) 
    ocr_button.clicked.connect(lambda: threading.Thread(target=start_ocr, daemon=True).start())
    layout.addWidget(ocr_button)

    stop_ocr_button = QPushButton("Остановить OCR")
    stop_ocr_button.setEnabled(False) 
    stop_ocr_button.clicked.connect(stop_ocr)
    layout.addWidget(stop_ocr_button)

    global question_label, answer_label, status_label
    status_label = QLabel("Статус: Остановлен")
    status_label.setStyleSheet("color: red;") 
    layout.addWidget(status_label)

    question_label = QLabel("")
    question_label.setWordWrap(True)
    layout.addWidget(question_label)

    answer_label = QLabel("")
    answer_label.setWordWrap(True)
    layout.addWidget(answer_label)

    window.setLayout(layout)

    global ocr_thread
    ocr_thread = OCRThread()
    ocr_thread.show_warning_signal.connect(lambda msg: QMessageBox.warning(window, "Предупреждение", msg))

    window.show()
    app.exec()

if __name__ == "__main__":
    main()
