def get_user_id_by_name(name):
    with open("user_data.json", 'r', encoding='utf-8') as f:
        data = json.load(f)

    for wrapper in data:
        memberships = wrapper.get("memberships", [])
        for member in memberships:
            user = member.get("user", {})
            fullname = user.get("fullname", "")
            if fullname.lower() == name.lower():
                return user.get("id")

    return None




#Im just saving this function here cus it took a while to get it to work and I might need it later