from typing import Literal
from datetime import datetime
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
class Input(BaseModel):model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
def normalize_email(value):
    import re
    value=value.strip().lower()
    if len(value)>100 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",value):
        raise ValueError('Enter a valid email address')
    local,domain=value.rsplit('@',1)
    if local.startswith('.') or local.endswith('.') or '..' in local or any(len(label)>63 for label in domain.split('.')):
        raise ValueError('Enter a valid email address')
    return value

class Login(Input):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=False)
    email:str=Field(min_length=3,max_length=100)
    password:str=Field(min_length=1,max_length=200)
    @field_validator('email')
    @classmethod
    def email_address(cls,value):return normalize_email(value)

class NewUser(Login):
    password:str=Field(min_length=12,max_length=200)
    role:Literal['admin','guard']='guard'

class VideoTest(Input):
    test_role:Literal['entry','exit']

class CameraInput(Input):
    name:str=Field(min_length=1,max_length=100)
    location:str=Field(min_length=1,max_length=160)
    purpose:Literal['Entry Gate','Exit Gate','Entry and Exit']
    rtsp_url:str|None=Field(default=None,max_length=2000)
class CameraTest(Input):rtsp_url:str=Field(min_length=8,max_length=2000)
class Zones(Input):
    entry:list[float]|None=None
    exit:list[float]|None=None
    @field_validator('entry','exit')
    @classmethod
    def line(cls,v):
        if v is not None and (len(v)!=4 or any(not 0<=x<=1 for x in v) or v[:2]==v[2:]):raise ValueError('Use distinct x1,y1,x2,y2 in [0,1]')
        return v
class Destination(Input):
    visit_purpose:Literal['Delivery','Relation','Maid/Caretaker']='Delivery'
    delivery_confirmed:Literal[True]
    flat:str=Field(min_length=1,max_length=40)
    resident_name:str=Field(min_length=1,max_length=120)
    resident_id:str|None=None
    company:str=Field(default='',max_length=120)
    notes:str=Field(default='',max_length=2000)
    visitor_name:str=Field(default='',max_length=120)
    visit_reason:str=Field(default='',max_length=500)
    expected_exit_at:datetime|None=None
    @field_validator('expected_exit_at')
    @classmethod
    def aware_exit(cls,value):
        if value is not None and value.tzinfo is None:raise ValueError('Exit time must include a timezone')
        return value
    @model_validator(mode='after')
    def validate_visitor_details(self):
        if self.visit_purpose in ('Relation','Maid/Caretaker') and (not self.visitor_name or not self.visit_reason):
            raise ValueError('Visitor name and reason for the visit are required for guests and maids/caretakers')
        if any(ord(ch)<32 or ord(ch)==127 for ch in self.visitor_name+self.visit_reason):
            raise ValueError('Control characters are not allowed in visitor details')
        return self
class Manual(Input):
    camera_id:str|None=None
    reason:str=Field(min_length=5,max_length=500)
class Completion(Input):
    confirmed:Literal[True]
    reason:str=Field(min_length=5,max_length=500)
    observation_id:str|None=None
class Enrollment(Input):
    authorized:Literal[True]
    authorization:str=Field(min_length=15,max_length=1000)
    retention_days:int=Field(ge=1,le=90)
class ResidentInput(Input):
    name:str=Field(min_length=1,max_length=120)
    flat:str=Field(min_length=1,max_length=40)
    phone:str=Field(min_length=10,max_length=20)
    @field_validator('phone')
    @classmethod
    def phone_number(cls,value):
        import re
        value=re.sub(r'[ ()-]','',value)
        if re.fullmatch(r'[6-9][0-9]{9}',value):value='+91'+value
        if not re.fullmatch(r'\+[1-9][0-9]{7,14}',value):raise ValueError('Use a 10-digit Indian mobile number or an international number with +country code')
        return value
    @field_validator('flat')
    @classmethod
    def normalize_flat(cls,value):return value.upper()
    @field_validator('name','flat')
    @classmethod
    def no_control_characters(cls,value):
        if any(ord(ch)<32 or ord(ch)==127 for ch in value):raise ValueError('Control characters are not allowed')
        return value

class OTPRequest(Input):
    resident_id:str=Field(min_length=1,max_length=36)
    delivery_confirmed:Literal[True]

class OTPCheck(Input):
    challenge_id:str=Field(min_length=1,max_length=36)
    code:str=Field(pattern=r'^[0-9]{6}$')


class MapFlat(Input):
    flat:str=Field(min_length=1,max_length=40)
    @field_validator('flat')
    @classmethod
    def normalize_flat(cls,value):
        if any(ord(ch)<32 or ord(ch)==127 for ch in value):raise ValueError('Control characters are not allowed')
        return value.upper()

class MapPointInput(MapFlat):
    x:float=Field(ge=0,le=1,allow_inf_nan=False)
    y:float=Field(ge=0,le=1,allow_inf_nan=False)
