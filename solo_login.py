from testfire_robot import iniciar_driver, login

driver = iniciar_driver()
print("Resultado del login:", login(driver))
input("Enter para cerrar...")
driver.quit()
