from __init__ import *

def check_keys(*,key_true:str,key:str,ok_func:list,error_text:str):
	if key == key_true:
		return send_from_directory(ok_func[0],ok_func[1])
	return redirect(f'/wrong_key/'+error_text.replace("/'","")+'/') 