from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.models.database import Account, get_db
from pydantic import BaseModel

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

class AccountCreate(BaseModel):
    name: str
    account_type: str
    institution: str = None
    current_balance: float = 0.0

@router.post("/")
async def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    db_account = Account(**account.dict())
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account

@router.get("/")
async def list_accounts(db: Session = Depends(get_db)):
    return db.query(Account).all()
