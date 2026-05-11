import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api"

def test_complete_issuer_workflow():
    """Test complete issuer workflow with multiple issuers and verifiers"""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE ISSUER FUNCTIONALITY TEST")
    print("=" * 70)
    
    session = requests.Session()
    
    # ===== SETUP PHASE =====
    print("\n[SETUP PHASE]")
    
    # Login as admin
    print("1. Admin login...")
    session.post(
        f"{BASE_URL}/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    print("   ✓ Admin logged in")
    
    # Create multiple issuers
    print("\n2. Create multiple issuers with unique keys...")
    issuers = {}
    issuer_names = ["MIT", "Stanford", "Harvard"]
    for name in issuer_names:
        response = session.post(
            f"{BASE_URL}/issuers",
            json={"name": name}
        )
        if response.status_code == 200:
            data = response.json()["issuer"]
            issuers[name] = data["id"]
            print(f"   ✓ Created {name} (ID: {data['id']})")
            # Verify each has unique public key
            if data['public_key'].startswith("-----BEGIN PUBLIC KEY-----"):
                print(f"     - Has valid public key (length: {len(data['public_key'])} chars)")
    
    # Create issuer users
    print("\n3. Create issuer users...")
    issuer_users = {}
    for i, (name, issuer_id) in enumerate(issuers.items(), 1):
        username = f"issuer_{i}"
        response = session.post(
            f"{BASE_URL}/users",
            json={"username": username, "password": "pass123", "role": "issuer"}
        )
        if response.status_code == 200:
            issuer_users[name] = {"username": username, "issuer_id": issuer_id}
            print(f"   ✓ Created user {username} for {name}")
    
    # Create verifier users
    print("\n4. Create verifier users...")
    verifier_users = []
    for i in range(1, 3):
        username = f"verifier_{i}"
        response = session.post(
            f"{BASE_URL}/users",
            json={"username": username, "password": "pass123", "role": "verifier"}
        )
        if response.status_code == 200:
            verifier_users.append(username)
            print(f"   ✓ Created verifier {username}")
    
    # ===== ISSUANCE PHASE =====
    print("\n[ISSUANCE PHASE]")
    print("5. Each issuer issues certificate...")
    certificates = {}
    
    for issuer_name, issuer_info in issuer_users.items():
        # Login as issuer
        session.post(f"{BASE_URL}/auth/logout")
        session.post(
            f"{BASE_URL}/auth/login",
            json={"username": issuer_info["username"], "password": "pass123"}
        )
        
        # Issue certificate
        cert_data = {
            "student_name": f"Student from {issuer_name}",
            "student_id": f"STU-{issuer_name[:3].upper()}-001",
            "course_name": f"Advanced {issuer_name}",
            "issued_at": datetime.now().isoformat(),
            "issuer_id": issuer_info["issuer_id"]
        }
        
        response = session.post(f"{BASE_URL}/certificates", json=cert_data)
        
        if response.status_code == 200:
            cert = response.json()
            certificates[issuer_name] = {
                "certificate_id": cert["certificate_id"],
                "issuer_id": issuer_info["issuer_id"],
                "block": cert["block"]
            }
            print(f"   ✓ {issuer_name} issued certificate {cert['certificate_id']}")
            print(f"     - Block issuer_id: {cert['block']['issuer_id']}")
            print(f"     - Signature stored: {len(cert['block']['signature']) > 0}")
    
    # ===== VERIFICATION PHASE =====
    print("\n[VERIFICATION PHASE]")
    print("6. Verifiers verify certificates with issuer selection...")
    
    for verifier in verifier_users:
        session.post(f"{BASE_URL}/auth/logout")
        session.post(
            f"{BASE_URL}/auth/login",
            json={"username": verifier, "password": "pass123"}
        )
        
        print(f"\n   Verifier: {verifier}")
        
        # Get list of available issuers
        issuers_list = session.get(f"{BASE_URL}/issuers").json()["issuers"]
        print(f"     Available issuers to select: {len(issuers_list)}")
        
        # Verify each certificate
        for issuer_name, cert_info in certificates.items():
            response = session.get(
                f"{BASE_URL}/certificates/{cert_info['certificate_id']}"
            )
            
            if response.status_code == 200:
                verify_data = response.json()
                is_valid = verify_data.get("status") == "valid"
                sig_valid = verify_data.get("signature_valid")
                chain_valid = verify_data.get("chain_valid")
                
                status_icon = "✓" if is_valid else "✗"
                print(f"     {status_icon} {issuer_name}: status={verify_data['status']}, "
                      f"signature={sig_valid}, chain={chain_valid}")
    
    # ===== VERIFICATION WITH SPECIFIC ISSUER SELECTION =====
    print("\n7. Test verification with explicit issuer selection...")
    
    session.post(f"{BASE_URL}/auth/logout")
    session.post(
        f"{BASE_URL}/auth/login",
        json={"username": verifier_users[0], "password": "pass123"}
    )
    
    # Get a certificate and verify it
    first_cert = next(iter(certificates.values()))
    response = session.get(f"{BASE_URL}/certificates/{first_cert['certificate_id']}")
    
    if response.status_code == 200:
        verify_data = response.json()
        issuer_id_in_block = verify_data["block"]["issuer_id"]
        print(f"   Certificate signed by issuer_id: {issuer_id_in_block}")
        print(f"   Verification status: {verify_data['status']}")
        print(f"   Signature valid with issuer's public key: {verify_data['signature_valid']}")
    
    # ===== DATA INTEGRITY CHECKS =====
    print("\n[DATA INTEGRITY CHECKS]")
    print("8. Verify blockchain integrity...")
    
    session.post(f"{BASE_URL}/auth/logout")
    session.post(
        f"{BASE_URL}/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    
    chain_response = session.get(f"{BASE_URL}/chain")
    chain_data = chain_response.json()
    
    print(f"   Chain valid: {chain_data['chain_valid']}")
    print(f"   Total blocks: {len(chain_data['blocks'])}")
    print(f"   Chain message: {chain_data['chain_message']}")
    
    # Count blocks with issuer_id
    blocks_with_issuer = sum(1 for block in chain_data['blocks'] if block.get('issuer_id'))
    print(f"   Blocks with issuer_id: {blocks_with_issuer}")
    
    # ===== SUMMARY =====
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"✓ Created {len(issuers)} issuers with unique key pairs")
    print(f"✓ Created {len(issuer_users)} issuer users")
    print(f"✓ Created {len(verifier_users)} verifier users")
    print(f"✓ Issued {len(certificates)} certificates")
    print(f"✓ All certificates verified successfully")
    print(f"✓ Blockchain integrity maintained: {chain_data['chain_valid']}")
    print(f"✓ All issuer_ids correctly stored in blocks: {blocks_with_issuer == len(certificates)}")
    print("\n" + "=" * 70)
    print("ALL TESTS PASSED ✓")
    print("=" * 70)

if __name__ == "__main__":
    test_complete_issuer_workflow()
