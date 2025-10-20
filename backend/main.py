from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, func, Date
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from datetime import datetime, timedelta, date
import os
import shutil
from typing import Optional, List, Dict

# ---------------- CONFIG & SETUP ----------------
SECRET_KEY = "a_very_secret_key_that_is_long_and_secure"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "media")
os.makedirs(MEDIA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

app = FastAPI(title="EcoLearners Platform API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- DATABASE MODELS (WITH FIX) ----------------
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    hashed_password = Column(String)
    role = Column(String, default="student")
    points = Column(Integer, default=0)
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")

class UserProfile(Base):
    __tablename__ = "user_profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    register_number = Column(String, nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String, nullable=True)
    address = Column(String, nullable=True)
    residence = Column(String, nullable=True)
    user = relationship("User", back_populates="profile")

class Lesson(Base):
    __tablename__ = "lessons"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    video_url = Column(String)
    quiz = relationship("Quiz", back_populates="lesson", uselist=False, cascade="all, delete-orphan")

class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(Integer, primary_key=True, index=True)
    lesson_id = Column(Integer, ForeignKey("lessons.id"), unique=True)
    lesson = relationship("Lesson", back_populates="quiz")
    questions = relationship("Question", back_populates="quiz", cascade="all, delete-orphan")

class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"))
    question_text = Column(Text, nullable=False)
    quiz = relationship("Quiz", back_populates="questions")

class QuizSubmission(Base):
    __tablename__ = "quiz_submissions"
    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    submitted_at = Column(DateTime, default=datetime.utcnow)
    score = Column(Integer, nullable=True)
    is_graded = Column(Boolean, default=False)
    answers = relationship("Answer", back_populates="submission", cascade="all, delete-orphan")
    student = relationship("User")
    quiz = relationship("Quiz")

class Answer(Base):
    __tablename__ = "answers"
    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey("quiz_submissions.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    answer_text = Column(Text)
    submission = relationship("QuizSubmission", back_populates="answers")
    question = relationship("Question")

class AssignedTask(Base):
    __tablename__ = "assigned_tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    description = Column(Text)
    points = Column(Integer)
    deadline = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    submissions = relationship("TaskSubmission", back_populates="task")

class TaskSubmission(Base):
    __tablename__ = "task_submissions"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("assigned_tasks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    filename = Column(String)
    approved = Column(Boolean, default=False)
    points_awarded = Column(Integer, default=0)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    task = relationship("AssignedTask", back_populates="submissions")
    student = relationship("User")

class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    url = Column(String)
    skill = Column(String)
    # THIS FIXES THE CRASH: When a game is deleted, all its scores are also deleted.
    scores = relationship("GameScore", back_populates="game", cascade="all, delete-orphan")

class GameScore(Base):
    __tablename__ = "game_scores"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    game_id = Column(Integer, ForeignKey("games.id"))
    score = Column(Integer)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    game = relationship("Game", back_populates="scores")
    student = relationship("User")

class Notice(Base):
    __tablename__ = "notices"
    id = Column(Integer, primary_key=True, index=True)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ---------------- HELPERS ----------------
def hash_password(pw: str):
    return pwd_context.hash(pw.encode('utf-8')[:72])

def verify_password(plain, hashed):
    return pwd_context.verify(plain.encode('utf-8')[:72], hashed)

# ---------------- DEMO DATA ----------------
with SessionLocal() as db:
    if not db.query(User).first():
        student = User(email="demo@student.local", name="Demo Student", hashed_password=hash_password("demo1234"), role="student")
        teacher = User(email="teacher@school.local", name="Demo Teacher", hashed_password=hash_password("teacher1234"), role="teacher")
        db.add_all([student, teacher])
        db.commit()
        
        student_profile = UserProfile(user_id=student.id)
        db.add(student_profile)
        db.commit()

    if not db.query(Game).first():
        db.add_all([
            Game(name="Typing Speed Test", url="https://play.typeracer.com/", skill="Typing Speed"),
            Game(name="Logical Puzzles", url="https://www.brainzilla.com/logic/logic-grid-puzzles/", skill="Logical Skill"),
            Game(name="Math Playground", url="https://www.mathplayground.com/", skill="Mathematical Ability")
        ])
        db.commit()

    if not db.query(Notice).first():
        db.add(Notice(message="Welcome to the new EcoLearners Platform! Please complete your profile."))
        db.commit()
        
# ---------------- PYDANTIC SCHEMAS ----------------

class Token(BaseModel):
    access_token: str; token_type: str
class UserProfileIn(BaseModel):
    name: str; register_number: Optional[str] = None; date_of_birth: Optional[date] = None; gender: Optional[str] = None; address: Optional[str] = None; residence: Optional[str] = None
class UserProfileOut(BaseModel):
    register_number: Optional[str] = None; date_of_birth: Optional[date] = None; gender: Optional[str] = None; address: Optional[str] = None; residence: Optional[str] = None; age: Optional[int] = None
    class Config: from_attributes = True
class UserProfileResponse(UserProfileOut):
    name: str
class UserOut(BaseModel):
    id: int; email: str; name: Optional[str]; role: str; points: int; profile: Optional[UserProfileOut] = None
    class Config: from_attributes = True
class GameOut(BaseModel):
    id: int; name: str; url: str; skill: str
    class Config: from_attributes = True
class GameScoreIn(BaseModel):
    game_id: int; score: int
class NoticeOut(BaseModel):
    message: str; created_at: datetime
    class Config: from_attributes = True
class LessonCreate(BaseModel):
    title: str; description: str; video_url: str
class LessonOut(BaseModel):
    id: int; title: str; description: str; video_url: str
    class Config: from_attributes = True
class QuestionCreate(BaseModel):
    question_text: str
class QuizCreate(BaseModel):
    questions: List[QuestionCreate]
class QuestionOut(BaseModel):
    id: int; question_text: str
    class Config: from_attributes = True
class QuizOut(BaseModel):
    id: int; lesson_id: int; questions: List[QuestionOut]; total_points: int
    class Config: from_attributes = True
class AnswerIn(BaseModel):
    question_id: int; answer_text: str
class QuizSubmissionIn(BaseModel):
    answers: List[AnswerIn]
class QuizSubmissionScore(BaseModel):
    score: int
class QuizSubmissionStatus(BaseModel):
    is_graded: bool; score: Optional[int]
    class Config: from_attributes = True
class LessonQuizResponse(BaseModel):
    lesson: LessonOut; quiz: Optional[QuizOut] = None; submission: Optional[QuizSubmissionStatus] = None
class TaskCreate(BaseModel):
    title: str; description: str; points: int; deadline: date
class TaskSubmissionStatus(BaseModel):
    approved: bool; points_awarded: int
    class Config: from_attributes = True
class AssignedTaskForStudent(BaseModel):
    id: int; title: str; description: str; points: int; deadline: datetime; submission_status: Optional[TaskSubmissionStatus] = None
    class Config: from_attributes = True
class TaskGradeIn(BaseModel):
    points: int

# ---------------- AUTHENTICATION & PROFILE ----------------
def create_access_token(subject: str):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": subject, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    # ... (same as before)
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None: raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.email == email).first()
    if user is None: raise credentials_exception
    return user

@app.post("/login/{role}", response_model=Token)
def login(role: str, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username).first()
    if not user or user.role != role or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail=f"Invalid {role} credentials")
    return {"access_token": create_access_token(user.email), "token_type": "bearer"}

@app.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

@app.get("/profile", response_model=UserProfileResponse)
def get_profile(user: User = Depends(get_current_user)):
    # ... (same as before)
    if not user.profile:
        return UserProfileResponse(name=user.name)
    age = None
    if user.profile.date_of_birth:
        today = date.today()
        dob = user.profile.date_of_birth
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return UserProfileResponse(name=user.name, register_number=user.profile.register_number, date_of_birth=user.profile.date_of_birth, gender=user.profile.gender, address=user.profile.address, residence=user.profile.residence, age=age)

@app.put("/profile", response_model=UserProfileResponse)
def update_profile(profile_data: UserProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # ... (same as before)
    user.name = profile_data.name
    if not user.profile:
        user.profile = UserProfile(user_id=user.id)
    user.profile.register_number = profile_data.register_number
    user.profile.date_of_birth = profile_data.date_of_birth
    user.profile.gender = profile_data.gender
    user.profile.address = profile_data.address
    user.profile.residence = profile_data.residence
    db.add(user)
    db.commit()
    db.refresh(user)
    return get_profile(user=user)

# ---------------- GAMES, NOTICE BOARD, REPORTS ----------------
@app.get("/games", response_model=List[GameOut])
def get_games(db: Session = Depends(get_db)):
    return db.query(Game).all()
@app.post("/games", status_code=201)
def add_game(name: str = Form(...), url: str = Form(...), skill: str = Form(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'teacher': raise HTTPException(403, "Forbidden")
    new_game = Game(name=name, url=url, skill=skill)
    db.add(new_game); db.commit()
    return {"message": "Game added"}
@app.delete("/games/{game_id}", status_code=204)
def delete_game(game_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'teacher': raise HTTPException(403, "Forbidden")
    game = db.query(Game).get(game_id)
    if not game: raise HTTPException(404, "Game not found")
    db.delete(game); db.commit()
    return
@app.post("/games/submit-score", status_code=201)
def submit_game_score(score_in: GameScoreIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_score = GameScore(user_id=user.id, game_id=score_in.game_id, score=score_in.score)
    db.add(new_score); db.commit()
    return {"message": "Score submitted"}
@app.get("/notice", response_model=NoticeOut)
def get_latest_notice(db: Session = Depends(get_db)):
    notice = db.query(Notice).order_by(Notice.created_at.desc()).first()
    if not notice:
        return NoticeOut(message="No notices yet.", created_at=datetime.utcnow())
    return notice
@app.post("/notice", status_code=201)
def post_notice(message: str = Form(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'teacher': raise HTTPException(403, "Forbidden")
    db.query(Notice).delete()
    new_notice = Notice(message=message)
    db.add(new_notice); db.commit()
    return {"message": "Notice posted"}
@app.get("/reports/students", response_model=List[UserOut])
def get_all_students(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'teacher': raise HTTPException(403, "Forbidden")
    return db.query(User).filter(User.role == 'student').all()

class StudentReportOut(BaseModel):
    user: UserOut; academic_score: int; soft_skills: Dict[str, float]
@app.get("/reports/student/{student_id}", response_model=StudentReportOut)
def get_student_report(student_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'teacher' and user.id != student_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    student = db.query(User).get(student_id)
    if not student or student.role != 'student': raise HTTPException(404, "Student not found")
    task_points = db.query(func.sum(TaskSubmission.points_awarded)).filter(TaskSubmission.user_id == student_id).scalar() or 0
    quiz_points = db.query(func.sum(QuizSubmission.score)).filter(QuizSubmission.user_id == student_id).scalar() or 0
    academic_score = task_points + quiz_points
    game_scores = db.query(GameScore).filter(GameScore.user_id == student_id).all()
    skills = {}
    for score in game_scores:
        if score.game:  # THIS IS THE FIX: Check if the game exists before accessing it
            if score.game.skill not in skills: skills[score.game.skill] = []
            skills[score.game.skill].append(score.score)
    avg_skills = {skill: sum(scores)/len(scores) for skill, scores in skills.items()}
    return StudentReportOut(user=student, academic_score=academic_score, soft_skills=avg_skills)

# --- LESSONS, QUIZZES, TASKS, GRADING ---
# ... (All these functions are correct and remain the same)
@app.get("/lessons", response_model=List[LessonOut])
def list_lessons(db: Session = Depends(get_db)): return db.query(Lesson).all()
@app.post("/lessons", response_model=LessonOut, status_code=201)
def create_lesson(lesson: LessonCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(403, "Forbidden")
    new_lesson = Lesson(**lesson.dict()); db.add(new_lesson); db.commit(); db.refresh(new_lesson); return new_lesson
@app.post("/lessons/{lesson_id}/quizzes", status_code=201)
def create_or_update_quiz(lesson_id: int, quiz_in: QuizCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(403, "Forbidden")
    lesson = db.query(Lesson).get(lesson_id)
    if not lesson: raise HTTPException(404, "Lesson not found")
    if lesson.quiz:
        db.query(Question).filter(Question.quiz_id == lesson.quiz.id).delete()
        quiz = lesson.quiz
    else:
        quiz = Quiz(lesson_id=lesson_id)
        db.add(quiz)
    for q_in in quiz_in.questions:
        quiz.questions.append(Question(question_text=q_in.question_text))
    db.commit()
    return {"message": "Quiz saved successfully"}
@app.get("/lessons/{lesson_id}/quiz", response_model=LessonQuizResponse)
def get_lesson_and_quiz(lesson_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lesson = db.query(Lesson).get(lesson_id)
    if not lesson: raise HTTPException(404, "Lesson not found")
    response = LessonQuizResponse(lesson=lesson)
    if lesson.quiz:
        total_points = len(lesson.quiz.questions) * 10
        response.quiz = QuizOut(id=lesson.quiz.id, lesson_id=lesson.id, questions=lesson.quiz.questions, total_points=total_points)
        submission = db.query(QuizSubmission).filter_by(user_id=user.id, quiz_id=lesson.quiz.id).first()
        if submission: response.submission = submission
    return response
@app.post("/quizzes/{quiz_id}/submit", status_code=201)
def submit_quiz(quiz_id: int, submission_in: QuizSubmissionIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    quiz = db.query(Quiz).get(quiz_id)
    if not quiz: raise HTTPException(status_code=404, detail="Quiz not found")
    if db.query(QuizSubmission).filter_by(user_id=user.id, quiz_id=quiz_id).first():
        raise HTTPException(status_code=400, detail="You have already submitted this quiz.")
    try:
        new_submission = QuizSubmission(user_id=user.id, quiz_id=quiz_id)
        db.add(new_submission)
        db.flush()
        for ans_in in submission_in.answers:
            db.add(Answer(submission_id=new_submission.id, question_id=ans_in.question_id, answer_text=ans_in.answer_text))
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    return {"message": "Quiz submitted for review"}
@app.post("/tasks/assign", status_code=201)
def assign_task(task: TaskCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(status_code=403, detail="Forbidden")
    if task.deadline < date.today(): raise HTTPException(status_code=400, detail="Deadline cannot be in the past.")
    try:
        deadline_datetime = datetime.combine(task.deadline, datetime.max.time())
        new_task = AssignedTask(title=task.title, description=task.description, points=task.points, deadline=deadline_datetime)
        db.add(new_task)
        db.commit()
        db.refresh(new_task)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    return {"message": "Task assigned", "task_id": new_task.id}
@app.get("/tasks", response_model=List[AssignedTaskForStudent])
def list_tasks_for_student(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tasks = db.query(AssignedTask).order_by(AssignedTask.deadline.asc()).all()
    response = []
    for task in tasks:
        submission = db.query(TaskSubmission).filter_by(user_id=user.id, task_id=task.id).first()
        task_data = AssignedTaskForStudent.from_orm(task)
        if submission: task_data.submission_status = TaskSubmissionStatus.from_orm(submission)
        response.append(task_data)
    return response
@app.get("/tasks/all", response_model=List[AssignedTaskForStudent])
def list_all_tasks_for_teacher(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != 'teacher': raise HTTPException(403, "Forbidden")
    return db.query(AssignedTask).order_by(AssignedTask.created_at.desc()).all()
@app.post("/tasks/{task_id}/submit", status_code=201)
def submit_task(task_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(TaskSubmission).filter_by(user_id=user.id, task_id=task_id).first():
        raise HTTPException(400, "Already submitted.")
    filename = f"{user.id}_{task_id}_{file.filename}"
    with open(os.path.join(MEDIA_DIR, filename), "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    submission = TaskSubmission(user_id=user.id, task_id=task_id, filename=filename)
    db.add(submission); db.commit()
    return {"message": "Submission successful"}
@app.get("/submissions/tasks")
def get_task_submissions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(403, "Forbidden")
    subs = db.query(TaskSubmission).filter_by(approved=False).all()
    return [{"id": s.id, "student_name": s.student.name, "task_title": s.task.title, "filename": s.filename, "max_points": s.task.points} for s in subs]
@app.post("/submissions/tasks/{submission_id}/grade")
def grade_task_submission(submission_id: int, grade: TaskGradeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(403, "Forbidden")
    sub = db.query(TaskSubmission).get(submission_id)
    if not sub or sub.approved: raise HTTPException(404, "Not found or already graded.")
    sub.approved = True; sub.points_awarded = grade.points
    sub.student.points += grade.points
    db.commit()
    return {"message": "Task graded"}
@app.get("/submissions/quizzes")
def get_quiz_submissions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(403, "Forbidden")
    subs = db.query(QuizSubmission).filter_by(is_graded=False).all()
    return [{"id": s.id, "student_name": s.student.name, "quiz_title": s.quiz.lesson.title} for s in subs]
class AnswerOut(BaseModel):
    question_text: str; answer_text: str
    class Config: from_attributes = True
@app.get("/submissions/quizzes/{submission_id}")
def get_quiz_submission_details(submission_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(403, "Forbidden")
    sub = db.query(QuizSubmission).get(submission_id)
    if not sub: raise HTTPException(404, "Not found")
    answers_out = []
    for ans in sub.answers:
        answers_out.append({"question_text": ans.question.question_text, "answer_text": ans.answer_text})
    return {"id": sub.id, "student_name": sub.student.name, "quiz_title": sub.quiz.lesson.title, "answers": answers_out, "total_points": len(sub.quiz.questions) * 10}
@app.post("/submissions/quizzes/{submission_id}/grade")
def grade_quiz_submission(submission_id: int, grade: QuizSubmissionScore, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "teacher": raise HTTPException(403, "Forbidden")
    sub = db.query(QuizSubmission).get(submission_id)
    if not sub or sub.is_graded: raise HTTPException(404, "Not found or already graded.")
    sub.is_graded = True; sub.score = grade.score
    sub.student.points += grade.score
    db.commit()
    return {"message": "Quiz graded"}
@app.get("/leaderboard", response_model=List[UserOut])
def leaderboard(db: Session = Depends(get_db)):
    return db.query(User).filter(User.role == 'student').order_by(User.points.desc()).limit(10).all()

from fastapi.staticfiles import StaticFiles
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


